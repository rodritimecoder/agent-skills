"""Distil your notes into the questions they answer, through claude -p.

    python distil.py path/to/your/notes
    python distil.py path/to/your/notes --limit 20

One short call per note, subfolders included. Every answer is checked before it
is kept: it needs a question and a quote, and the quote has to be in the note
word for word. Anything else is dropped and named. A note already distilled is
skipped unless it has changed since. The index is rebuilt at the end.

State lives in distilled/.state.json, keyed by the note's path inside your
notes folder with the sha256 of what was read.
"""

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from build_index import normalise, note_files, parse_entry, utf8_out  # noqa: E402

DISTILLED = HERE / "distilled"
STATE = DISTILLED / ".state.json"
PROMPT = HERE / "distil-prompt.md"
CONFIG = HERE.parent / "digest" / "config.json"
import urllib.request

CALL_TIMEOUT = int(os.environ.get("CALL_TIMEOUT", "120"))
CHAT_URL = os.environ.get("CHAT_URL", "http://127.0.0.1:8000/v1/chat/completions")
DEFAULT_MODEL = os.environ.get("CHAT_MODEL", "qwen3.6-35b")


def model_name():
    """The model name to use for chat completions."""
    return DEFAULT_MODEL


def ask(model, prompt_text, payload):
    """One chat completion call via local OpenAI-compatible endpoint.

    Uses temperature: 0.0 and structured JSON extraction for strict quote verification.
    """
    m = DEFAULT_MODEL if not model or model in ("sonnet", "haiku", "opus") else model
    system_msg = (
        "You are an exact note distillation engine. "
        "Read the note carefully. Extract 1-3 questions someone would search for months later, "
        "a 1-line summary, a rule or key insight if present, and an EXACT quote copied verbatim "
        "word-for-word from the note that proves the answer. "
        "CRITICAL INVARIANT: The quote MUST be an exact verbatim substring from the provided note text. "
        "Never paraphrase, modify or trim words inside the quote. "
        "If no exact quote proves the answer, return an empty quote and empty questions.\n\n"
        "Respond STRICTLY with a valid JSON object matching this schema:\n"
        "{\n"
        '  "source": "<source file name>",\n'
        '  "questions": ["<question 1>", "<question 2>"],\n'
        '  "summary": "<one-line summary>",\n'
        '  "rule": "<rule or key takeaway, or empty string>",\n'
        '  "quote": "<exact verbatim quote from text>"\n'
        "}"
    )

    body = {
        "model": m,
        "temperature": 0.0,
        "messages": [
            {"role": "system", "content": system_msg},
            {"role": "user", "content": f"{prompt_text}\n\n---\n\n{payload}"},
        ],
        "response_format": {"type": "json_object"},
    }

    endpoints = [CHAT_URL]
    if "8000" in CHAT_URL:
        endpoints.append("http://127.0.0.1:8080/v1/chat/completions")
    elif "8080" in CHAT_URL:
        endpoints.append("http://127.0.0.1:8000/v1/chat/completions")

    content = None
    last_err = None
    for endpoint in endpoints:
        try:
            req = urllib.request.Request(
                endpoint,
                data=json.dumps(body).encode("utf-8"),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req, timeout=CALL_TIMEOUT) as resp:
                res_data = json.loads(resp.read().decode("utf-8"))
                content = res_data["choices"][0]["message"]["content"].strip()
                break
        except Exception as exc:
            last_err = exc

    if content is None:
        raise RuntimeError(f"chat completion failed on {endpoints}: {last_err}")

    # Convert structured JSON into standard markdown format expected by parse_entry
    try:
        parsed = json.loads(content)
        lines = []
        if parsed.get("source"):
            lines.append(f"source: {parsed['source']}")
        for q in parsed.get("questions", []):
            lines.append(f"- {q}")
        if parsed.get("summary"):
            lines.append(f"summary: {parsed['summary']}")
        if parsed.get("rule"):
            lines.append(f"rule: {parsed['rule']}")
        if parsed.get("quote"):
            lines.append(f'quote: "{parsed["quote"]}"')
        return "\n".join(lines)
    except Exception:
        return content


def slug_for(rel):
    """A file name for a note's distilled entry, unique across subfolders."""
    stem = rel[:-3] if rel.endswith(".md") else rel
    return (re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "note") + ".md"


def load_state():
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_state(state):
    DISTILLED.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")


def render(rel, entry):
    """The distilled entry as build_index reads it."""
    lines = [f"source: {rel}"]
    lines += [f"- {q}" for q in entry["questions"]]
    if entry.get("summary"):
        lines.append(f"summary: {entry['summary']}")
    if entry.get("rule"):
        lines.append(f"rule: {entry['rule']}")
    lines.append(f'quote: "{entry["quote"]}"')
    return "\n".join(lines) + "\n"


def distil_one(path, rel, model, prompt_text):
    """Distil one note. Returns the entry text, or None with the reason said."""
    body = path.read_text(encoding="utf-8", errors="replace")
    sample = body[:15000]
    entry = parse_entry(ask(model, prompt_text, f"file name: {rel}\n\n{sample}"))
    if not entry.get("source"):
        entry["source"] = rel
    quote = entry.get("quote", "")
    if not entry["questions"] or not quote:
        print(f"dropped {rel}: no question or no quote")
        return None
    if normalise(quote) not in normalise(body):
        print(f"dropped {rel}: quote not found in the note")
        return None
    return render(rel, entry)


def run(corpus, paths=None, limit=None, rebuild=True):
    """Distil the notes under corpus that have changed. Returns the counts."""
    corpus = Path(corpus).resolve()
    if not corpus.is_dir():
        raise RuntimeError(f"not a folder: {corpus}")
    prompt_text = PROMPT.read_text(encoding="utf-8")
    model = model_name()
    files = [Path(p).resolve() for p in paths] if paths else note_files(corpus)

    state = load_state()
    counts = {"distilled": 0, "skipped": 0, "dropped": 0}
    for path in files:
        if limit is not None and counts["distilled"] + counts["dropped"] >= limit:
            counts["skipped"] += 1
            continue
        rel = path.relative_to(corpus).as_posix()
        body = path.read_bytes()
        digest = hashlib.sha256(body).hexdigest()
        known = state.get(rel)
        slug = slug_for(rel)
        if known and known.get("sha256") == digest and (DISTILLED / slug).is_file():
            counts["skipped"] += 1
            continue
        try:
            text = distil_one(path, rel, model, prompt_text)
        except Exception as exc:  # one bad note never stops the run
            print(f"dropped {rel}: {type(exc).__name__} {exc}")
            counts["dropped"] += 1
            continue
        if text is None:
            counts["dropped"] += 1
            continue
        DISTILLED.mkdir(parents=True, exist_ok=True)
        (DISTILLED / slug).write_text(text, encoding="utf-8")
        state[rel] = {"sha256": digest, "slug": slug}
        counts["distilled"] += 1
        print(f"distilled {rel} -> distilled/{slug}")
    save_state(state)

    print(
        f"distilled {counts['distilled']}, skipped {counts['skipped']}, "
        f"dropped {counts['dropped']}"
    )
    if rebuild and counts["distilled"]:
        rebuild_index(corpus)
    return counts


def rebuild_index(corpus):
    """Rebuild the index over a folder. The index is disposable, always."""
    subprocess.run(
        [sys.executable, str(HERE / "build_index.py"), "--corpus", str(corpus)],
        check=False,
    )


def main():
    utf8_out()
    ap = argparse.ArgumentParser(description="Distil notes into questions.")
    ap.add_argument("corpus", help="the folder your markdown notes are in")
    ap.add_argument("--limit", type=int, default=None, help="stop after N notes")
    args = ap.parse_args()
    try:
        run(args.corpus, limit=args.limit)
    except Exception as exc:
        sys.exit(f"distil: {exc}")


if __name__ == "__main__":
    main()
