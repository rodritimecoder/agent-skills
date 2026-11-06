#!/usr/bin/env python3
"""
judge.py — The Fresh-Context Unbiased Judge (Kem's Step 4)
Evaluates worker diffs against [REQ-XX] acceptance criteria with zero conversational baggage.
Fires Kem's pink arrow (SENT BACK) with a rejection delta if gates fail.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_PATH = Path(__file__).resolve()
sys.path.insert(0, str(SCRIPT_PATH.parent))
import kanban

DEFAULT_MODEL = "flash"


def collect_evaluation_payload(card_file: Path, target_dir: Path) -> dict:
    card = kanban.parse_card(card_file)

    # 1. Collect Git Diff
    diff = ""
    try:
        res = subprocess.run(["git", "-C", str(target_dir), "diff", "HEAD~1"], capture_output=True, text=True)
        diff = res.stdout if res.returncode == 0 else ""
        if not diff.strip():
            res2 = subprocess.run(["git", "-C", str(target_dir), "diff"], capture_output=True, text=True)
            diff = res2.stdout if res2.returncode == 0 else ""
    except Exception:
        diff = ""

    # 2. Extract [REQ-XX] acceptance criteria
    reqs = card.get("reqs", [])

    return {
        "card_id": card["id"],
        "title": card["title"],
        "model": card.get("model", DEFAULT_MODEL),
        "requirements": reqs,
        "diff_snippet": diff[:3000] if diff else "No git diff detected.",
        "timestamp": datetime.now(timezone.utc).isoformat()
    }


JUDGE_SYSTEM = (
    "You are a fresh-context reviewer. You did not write this code and you have no stake in it. "
    "Judge the supplied diff against the stated requirements. Treat ticked checkboxes as claims, "
    "not evidence. Deterministic gate results are facts. Reply exactly in this format:\n"
    "VERDICT: APPROVED or REJECTED\n"
    "SCORE: 0-100\n"
    "DELTA: one sentence naming what must change, or NONE\n"
    "FEEDBACK: one sentence of evidence"
)


def build_judge_prompt(payload: dict, gate_report: list = None) -> str:
    lines = [f"Card: {payload['card_id']} — {payload['title']}", "", "Acceptance criteria:"]
    for req in payload.get("requirements", []):
        mark = "claimed done" if req.get("checked") else "open"
        lines.append(f"- {req['tag']} ({mark}): {req['text']}")
    if gate_report:
        lines += ["", "Deterministic gates:"]
        for gate in gate_report:
            detail = gate.get("command") or gate.get("path") or "not configured"
            lines.append(f"- {gate['name']}: {gate['status']} ({detail})")
    lines += ["", "Diff:", payload.get("diff_snippet") or "No git diff detected.", "", "Verdict:"]
    return "\n".join(lines)


def call_judge(prompt: str, model: str, judge_cmd: str = None, judge_url: str = None, timeout: int = 120) -> str:
    if judge_cmd:
        proc = subprocess.run(judge_cmd, shell=True, input=prompt, capture_output=True, text=True, timeout=timeout)
        if proc.returncode != 0:
            raise RuntimeError(f"judge command exited {proc.returncode}: {proc.stderr.strip()[:200]}")
        return proc.stdout

    url = judge_url or "http://127.0.0.1:8080/v1/chat/completions"
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": JUDGE_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0,
        "max_tokens": 600,
    }).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    return payload["choices"][0]["message"]["content"]


def parse_judge_output(raw: str) -> dict:
    verdict = re.search(r"VERDICT:\s*(APPROVED|REJECTED)", raw, re.IGNORECASE)
    score = re.search(r"SCORE:\s*(\d{1,3})", raw, re.IGNORECASE)
    delta = re.search(r"DELTA:\s*(.+)", raw, re.IGNORECASE)
    feedback = re.search(r"FEEDBACK:\s*(.+)", raw, re.IGNORECASE)
    if not verdict:
        raise ValueError("judge output has no VERDICT line")
    approved = verdict.group(1).upper() == "APPROVED"
    return {
        "verdict": verdict.group(1).upper(),
        "score": min(int(score.group(1)), 100) if score else 0,
        "rejection_delta": None if approved else (delta.group(1).strip() if delta else "No delta supplied."),
        "feedback": feedback.group(1).strip() if feedback else "",
    }


def evaluate_card(
    payload: dict,
    mock_verdict: str = None,
    gate_report: list = None,
    judge_cmd: str = None,
    judge_url: str = None,
    timeout: int = 120,
) -> dict:
    if mock_verdict in ("PASS", "FAIL"):
        if mock_verdict == "PASS":
            return {
                "verdict": "APPROVED",
                "score": 100,
                "rejection_delta": None,
                "feedback": "MOCK PASS: no model was consulted and nothing was verified.",
                "mock": True,
            }
        return {
            "verdict": "REJECTED",
            "score": 40,
            "rejection_delta": "MOCK FAIL: synthetic rejection delta.",
            "feedback": "MOCK FAIL: no model was consulted.",
            "mock": True,
        }

    prompt = build_judge_prompt(payload, gate_report)
    try:
        raw = call_judge(prompt, payload.get("model", DEFAULT_MODEL), judge_cmd, judge_url, timeout)
        evaluation = parse_judge_output(raw)
    except Exception as exc:
        return {
            "verdict": "REJECTED",
            "score": 0,
            "rejection_delta": f"judge unavailable: {exc}",
            "feedback": "Fail closed: no fresh-context verdict was produced.",
            "mock": False,
            "raw": "",
        }
    evaluation["mock"] = False
    evaluation["raw"] = raw[:4000]
    return evaluation


def record_verdict(card_file: Path, evaluation: dict) -> Path:
    content = card_file.read_text(encoding="utf-8")

    verdict_block = f"""
## Unbiased Judge Evaluation
- Status: COMPLETED
- Timestamp: {datetime.now(timezone.utc).isoformat()}
- Verdict: {evaluation['verdict']}
- Score: {evaluation['score']}/100
- Mock: {'yes' if evaluation.get('mock') else 'no'}
- Rejection Delta: {evaluation.get('rejection_delta') or 'NONE'}
- Feedback: {evaluation['feedback']}
"""

    if "## Unbiased Judge Evaluation" in content:
        content = re.sub(r"## Unbiased Judge Evaluation.*", verdict_block.strip(), content, flags=re.DOTALL)
    else:
        content += "\n" + verdict_block.strip() + "\n"

    card_file.write_text(content, encoding="utf-8")
    return card_file


def run_judge(
    card_id: str,
    target_dir: Path = None,
    model: str = DEFAULT_MODEL,
    mock: str = None,
    gate_report: list = None,
    judge_cmd: str = None,
    judge_url: str = None,
) -> bool:
    kanban_dir = kanban.find_kanban_root(target_dir)
    target = target_dir or kanban_dir.parent

    matches = list(kanban_dir.rglob(f"{card_id}*.md"))
    if not matches:
        sys.exit(f"❌ Error: Card '{card_id}' not found.")

    card_file = matches[0]
    payload = collect_evaluation_payload(card_file, target)
    payload["model"] = model

    print(f"\n⚖️ [Unbiased Judge] Evaluating {card_id} in a fresh context (Model: {model})...")
    evaluation = evaluate_card(payload, mock_verdict=mock, gate_report=gate_report, judge_cmd=judge_cmd, judge_url=judge_url)
    if evaluation.get("mock"):
        print("  ⚠️  MOCK VERDICT: this is a wiring test, not a judgement.")

    record_verdict(card_file, evaluation)

    if evaluation["verdict"] == "APPROVED":
        print(f"  ✅ VERDICT: APPROVED ({evaluation['score']}/100)")
        print(f"     {evaluation['feedback']}")
        kanban.move_card(card_id, "review", target_dir=target)
        return True
    else:
        print(f"  ❌ VERDICT: REJECTED ({evaluation['score']}/100)")
        print(f"  🏹 Kem's Pink Arrow: SENT BACK TO WORKER")
        print(f"     Delta: {evaluation['rejection_delta']}")
        if evaluation.get("feedback"):
            print(f"     Feedback: {evaluation['feedback']}")
        kanban.move_card(card_id, "picked_up", target_dir=target)
        return False


def main():
    parser = argparse.ArgumentParser(prog="agentic-judge", description="Fresh-Context Unbiased Judge (Kem's Step 4)")
    parser.add_argument("card_id", help="Card ID to evaluate (e.g. CARD-001)")
    parser.add_argument("target", nargs="?", default=".", help="Target project directory")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="Judge model tier (default: flash)")
    parser.add_argument("--mock", choices=["PASS", "FAIL"], help="Mock verdict for testing")
    parser.add_argument("--judge-cmd", default=os.environ.get("AGENTIC_JUDGE_CMD"), help="Command that reads the prompt on stdin and prints a verdict")
    parser.add_argument("--judge-url", default=os.environ.get("AGENTIC_JUDGE_URL", "http://127.0.0.1:8080/v1/chat/completions"), help="OpenAI-compatible endpoint for the fresh-context judge")

    args = parser.parse_args()
    target_path = Path(args.target).resolve()
    run_judge(
        args.card_id,
        target_dir=target_path,
        model=args.model,
        mock=args.mock,
        judge_cmd=args.judge_cmd,
        judge_url=args.judge_url,
    )


if __name__ == "__main__":
    main()
