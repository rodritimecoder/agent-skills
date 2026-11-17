#!/usr/bin/env python3
"""One typed decision from a local Jev-style model. Compact JSON out.

    decide.py "the state" "the question"                 # noul  -> P(true)
    decide.py "state" "question" '["low","mid","high"]'  # score -> expected level
    decide.py "state" "question" '{"billing":"desc", ...}'  # choice -> argmax + distribution
    decide.py --state-file notes.md --question "..." --options keep,draft,discard
    decide.py --model vllm ...     # vllm-d3-mini via /v1/systemone (:8083, default)
    decide.py --model jev ...      # Jev-Style-2B (no server needed)
    decide.py --model imajev ...   # Imajev-4B fallback (llama-server :8089)
    decide.py --batch q.json       # {"state": ..., "questions": {qid: {...}}}

Decision routing only ever targets the decision slots: the primary on :8083
(vllm/d3/pplx, native /v1/systemone) and the auxiliary on :8089 (onejev/imajev).
:8082 belongs to the OCR slot, so nothing here launches or posts to it; `jev`
runs a GGUF locally and needs no port at all.

Output:
    {"model": "imajev", "type": "choice", "answer": "billing",
     "p": {"billing": 0.96, "tech": 0.03, "sales": 0.01}, "confidence": 0.84}
"""
from __future__ import annotations

import argparse
import json
import math
import os
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

JEV_DIR = pathlib.Path(os.environ.get("JEV_DIR", "/home/rodri/build/jev-env"))

# ---- vllm-d3-mini backend (premier) ----------------------------------------
# Served by llama.cpp >= b11729 on VLLM_PORT (sh/vllm-d3-mini.sh). Native
# /v1/systemone: the model returns calibrated probabilities for all typed
# questions in one forward pass, so there is no letter readout or temperature
# divide - the server's numbers are already calibrated.
VLLM_PORT = int(os.environ.get("VLLM_PORT", "8083"))
PPLX_PORT = int(os.environ.get("PPLX_PORT", "8083"))
VLLM_BASE = f"http://127.0.0.1:{VLLM_PORT}"

# ---- OneJev1.5-4B / Imajev-4B decision backend -------------------------------
# Fallback behind vllm-d3-mini, served by the stock upstream llama.cpp build on
# IMAJEV_PORT (sh/onejev-4b.sh or sh/imajev-4b.sh). OneJev1.5-4B is the previous
# premier vision + decision model for calibrated routing.
# The readout is client-side. We present the options as letters, prefill the
# assistant turn with "Answer:" so the next token IS the choice, read the letter
# logits off completion_probabilities, divide by calibration temperature, then softmax.
IMAJEV_PORT = int(os.environ.get("IMAJEV_PORT", "8089"))
IMAJEV_BASE = f"http://127.0.0.1:{IMAJEV_PORT}"
IMAJEV_TEMPERATURE = float(os.environ.get("IMAJEV_TEMPERATURE", "1.3051569717552742"))
IMAJEV_IMAGE = os.environ.get("IMAJEV_IMAGE", "")
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"

# ---- Jev-Style-2B backend ---------------------------------------------------
# No server: `--model jev` runs the GGUF locally in JEV_DIR's venv (ask_jev).
# It used to squat on :8085, which is now the OCR slot - a decision server has # ports:ignore
# no business binding an OCR port.


def _concentration(probs):
    """1 - H(p)/log K: 0 for uniform, 1 for a point mass. Safe for K=1."""
    k = len(probs)
    if k <= 1:
        return 1.0
    ent = -math.fsum(p * math.log(p) for p in probs if p > 0)
    return min(1.0, max(0.0, 1 - ent / math.log(k)))


def ensure_vllm(port=VLLM_PORT, timeout=180):
    if _health(f"http://127.0.0.1:{port}/health"):
        return
    launcher = pathlib.Path("/run/media/rodri/AI/sh/vllm-d3-mini.sh")
    if not launcher.exists():
        raise SystemExit(f"vllm-d3-mini launcher missing: {launcher}")
    subprocess.Popen([str(launcher)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True,
                     env={**os.environ, "PORT": str(port)})
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health(f"http://127.0.0.1:{port}/health"):
            return
        time.sleep(1.0)
    raise SystemExit(f"vllm-d3-mini did not come up on :{port} - start sh/vllm-d3-mini.sh")


def _systemone_question(question, opts, typ):
    q = {"type": typ, "instructions": question}
    if typ == "choice":
        if isinstance(opts, dict):
            q["criteria"] = opts
        elif isinstance(opts, (list, tuple)):
            q["criteria"] = {str(o): None for o in opts}
    elif typ == "score":
        if not isinstance(opts, (list, tuple)):
            raise SystemExit("score needs a list of levels, lowest first")
        q["criteria"] = [str(o) for o in opts]
    return q


def ask_vllm(state, question, opts, typ, port=VLLM_PORT, timeout=180, images=None):
    """vllm-d3-mini: native /v1/systemone, already calibrated server-side.

    Returns the same internal shape as the other backends so flatten() and
    --cross-check treat every model identically.
    """
    payload = {"state": state, "questions": {"answer": _systemone_question(question, opts, typ)}}
    if images:
        payload["images"] = images
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/systemone",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        res = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"systemone {e.code}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"systemone unreachable on :{port} ({e.reason}) - start sh/vllm-d3-mini.sh")

    ans = (res.get("answers") or {}).get("answer")
    if not ans:
        raise SystemExit(f"systemone returned no answer: {str(res)[:300]}")
    return _map_systemone(ans, levels=opts if typ == "score" else None)


def _served_decision_type(port=VLLM_PORT):
    """Which decision model is actually on the port, and does it need a special client?

    pplx-decider checkpoints speak joint protocol v3, not the /v1/systemone
    layout, so the caller has to know which one is serving.
    """
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/models")
        data = json.load(urllib.request.urlopen(req, timeout=5))
    except Exception:
        return None
    entries = data.get("data") or []
    if not entries:
        return None
    entry = entries[0]
    modalities = ((entry.get("architecture") or {}).get("output_modalities")) or []
    if "decisions" not in modalities:
        return None
    path = entry.get("id")
    if not path:
        return None
    for directory in (
        pathlib.Path("/run/media/rodri/AI/skills/pplx-decider/scripts"),
        pathlib.Path.home() / ".pi/agent/skills/pplx-decider/scripts",
        pathlib.Path.home() / ".gemini/config/skills/pplx-decider/scripts",
    ):
        if not (directory / "gguf_meta.py").is_file():
            continue
        if str(directory) not in sys.path:
            sys.path.append(str(directory))
        try:
            import importlib

            return importlib.import_module("gguf_meta").decision_type(path)
        except Exception:
            continue
    return None


def _pplx_client():
    """Import the pplx-decider client (stdlib only) from the installed skill."""
    import importlib

    for directory in (
        pathlib.Path("/run/media/rodri/AI/skills/pplx-decider/scripts"),
        pathlib.Path.home() / ".pi/agent/skills/pplx-decider/scripts",
        pathlib.Path.home() / ".gemini/config/skills/pplx-decider/scripts",
    ):
        if not (directory / "pplx_decider.py").is_file():
            continue
        if str(directory) not in sys.path:
            sys.path.append(str(directory))
        try:
            return importlib.import_module("pplx_decider")
        except Exception:
            continue
    return None


def ensure_pplx(port=PPLX_PORT, timeout=10):
    if _health(f"http://127.0.0.1:{port}/health"):
        return
    launcher = pathlib.Path("/run/media/rodri/AI/sh/pplx-decider-flash.sh")
    if not launcher.exists():
        raise SystemExit(f"pplx-decider launcher missing: {launcher}")
    subprocess.Popen([str(launcher)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health(f"http://127.0.0.1:{port}/health"):
            return
        time.sleep(1.0)
    raise SystemExit(f"pplx-decider did not come up on :{port} - start sh/pplx-decider-flash.sh")


def ask_pplx(state, question, opts, typ, port=PPLX_PORT, timeout=180, images=None):
    """pplx-decider-flash v1.2: joint protocol v3, readout at each marker.

    The stock /v1/systemone path targets the older v1 prompt layout, so this
    backend drives the v1.2 protocol directly through the pplx-decider skill.
    """
    module = _pplx_client()
    if module is None:
        raise SystemExit("pplx-decider skill not found (expected scripts/pplx_decider.py)")
    client = module.PplxDecider(port=port, timeout=timeout)
    spec = _systemone_question(question, opts, typ)
    try:
        answers = client.decide(state, {"answer": spec})["answers"]
    except Exception as e:
        raise SystemExit(f"pplx-decider failed: {e}")
    ans = answers.get("answer")
    if not ans:
        raise SystemExit(f"pplx-decider returned no answer: {str(answers)[:300]}")
    return _map_systemone(
        {
            "type": typ,
            "noul": ans.get("noul"),
            "choice": ans.get("argmax"),
            "score": ans.get("score"),
            "confidence": _concentration(list(ans.get("probs", []))),
            "probabilities": {str(i): p for i, p in enumerate(ans.get("probs", []))},
        },
        levels=opts if typ == "score" else None,
        keys=ans.get("keys"),
    )


def _map_systemone(ans, levels=None, keys=None):
    """systemone answer object -> the internal backend shape.

    A systemone score is the expected *level index* (e.g. 2.28 of 4 levels), so
    it is re-expressed against the caller's level values when they are numeric.
    """
    typ = ans.get("type")
    if typ == "noul":
        p = float(ans.get("noul", 0.0))
        return {"type": "noul",
                "probabilities": {"true": round(p, 4), "false": round(1.0 - p, 4)},
                "confidence": round(abs(p - 0.5) * 2.0, 4)}
    if typ == "score":
        probs = ans.get("probabilities") or {}
        if levels:
            try:
                dist = {str(levels[int(k)]): round(v, 4) for k, v in probs.items()
                        if k.isdigit() and int(k) < len(levels)}
                scalar = sum(float(levels[int(k)]) * v for k, v in probs.items()
                             if k.isdigit() and int(k) < len(levels))
                if dist:
                    return {"type": "score", "score": round(scalar, 4),
                            "probabilities": dist,
                            "confidence": ans.get("confidence", 0.0)}
            except (TypeError, ValueError):
                pass
        return {"type": "score",
                "score": ans.get("score"),
                "probabilities": probs,
                "confidence": ans.get("confidence", 0.0)}
    probs = ans.get("probabilities") or {}
    if keys and typ != "score":
        # index-keyed probabilities -> option-keyed
        remapped = {}
        for k, v in probs.items():
            try:
                remapped[str(keys[int(k)])] = round(float(v), 4)
            except (IndexError, ValueError, TypeError):
                remapped[str(k)] = round(float(v), 4)
        probs = remapped
    return {"type": "choice",
            "answer": ans.get("choice"),
            "probabilities": probs,
            "confidence": ans.get("confidence", 0.0)}


def ask_vllm_batch(state, questions, port=VLLM_PORT, timeout=180, images=None):
    """One state, many typed questions, one forward pass. Questions may be a
    plain string (treated as noul) or a full systemone question object."""
    qs = {}
    for qid, spec in questions.items():
        qs[qid] = spec if isinstance(spec, dict) else {"type": "noul", "instructions": str(spec)}
    payload = {"state": state, "questions": qs}
    if images:
        payload["images"] = images
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/v1/systemone",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"})
    try:
        res = json.load(urllib.request.urlopen(req, timeout=timeout))
    except urllib.error.HTTPError as e:
        raise SystemExit(f"systemone {e.code}: {e.read().decode(errors='replace')[:300]}")
    except urllib.error.URLError as e:
        raise SystemExit(f"systemone unreachable on :{port} ({e.reason}) - start sh/vllm-d3-mini.sh")
    answers = res.get("answers") or {}
    out = {}
    for qid, ans in answers.items():
        spec = qs.get(qid) or {}
        lvls = spec.get("criteria") if spec.get("type") == "score" else None
        out[qid] = _map_systemone(ans, levels=lvls)
    return out


def _logaddexp(a, b):
    """math.logaddexp equivalent (not in the stdlib math module)."""
    if a == -math.inf:
        return b
    if b == -math.inf:
        return a
    m = max(a, b)
    return m + math.log(math.exp(a - m) + math.exp(b - m))


def ensure_imajev(port=IMAJEV_PORT, timeout=10):
    if _health(f"{IMAJEV_BASE}/health"):
        return
    launcher = pathlib.Path("/run/media/rodri/AI/sh/onejev-4b.sh")
    if not launcher.exists():
        launcher = pathlib.Path("/run/media/rodri/AI/sh/imajev-4b.sh")
    if not launcher.exists():
        raise SystemExit(f"decision launcher missing: {launcher}")
    subprocess.Popen([str(launcher)], stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _health(f"{IMAJEV_BASE}/health"):
            return
        time.sleep(1.0)
    raise SystemExit(f"decision server did not come up on :{port} - start sh/onejev-4b.sh")


def _letters_for(opts, typ):
    if typ == "noul":
        return {"A": "yes", "B": "no"}
    if isinstance(opts, dict):
        items = list(opts.items())
    elif isinstance(opts, (list, tuple)):
        items = list(enumerate(opts))
    else:
        items = []
    if not items:
        raise SystemExit("imajev needs options (or use --type noul)")
    if len(items) > len(_LETTERS):
        raise SystemExit(f"imajev supports at most {len(_LETTERS)} options")
    return {_LETTERS[i]: (str(k) if isinstance(opts, dict) else str(v))
            for i, (k, v) in enumerate(items)}


def ask_imajev(state, question, opts, typ, port=IMAJEV_PORT, timeout=180):
    """One typed decision from Imajev-4B. Letters in, calibrated options out."""
    import base64

    labels = _letters_for(opts, typ)
    lines = [f"Task: {question}", f"State: {state}"]
    for lt, lb in labels.items():
        lines.append(f"{lt}. {lb}")
    lines.append("Answer:")
    body = "\n".join(lines)

    prompt = (f"<|im_start|>user\n{body}<|im_end|>\n"
              f"<|im_start|>assistant\nAnswer:")

    req = urllib.request.Request(
        f"http://127.0.0.1:{port}/completion",
        data=json.dumps({"prompt": prompt, "max_tokens": 1,
                         "temperature": 0.0, "n_probs": 20}).encode(),
        headers={"Content-Type": "application/json"})
    res = json.load(urllib.request.urlopen(req, timeout=timeout))

    probs_raw = res.get("completion_probabilities") or []
    if not probs_raw:
        raise SystemExit("imajev returned no completion_probabilities")
    tops = probs_raw[0].get("top_logprobs") or []

    # Sum every surface form of each letter (" C", "C", " c", "c.").
    letter_lp = {}
    for t in tops:
        tok = (t.get("token") or "").strip().rstrip(".,:)!").strip()
        if len(tok) == 1 and tok.upper() in _LETTERS and tok.upper() in labels:
            lt = tok.upper()
            letter_lp[lt] = _logaddexp(letter_lp.get(lt, -math.inf), t["logprob"])

    if not letter_lp:
        raise SystemExit(
            "no option letters in top_logprobs - model did not answer with a letter. "
            f"tokens: {[t.get('token') for t in tops[:6]]}")

    # Calibrated softmax: divide by temperature, THEN normalise.
    mx = max(letter_lp.values())
    exps = {lt: math.exp((lp - mx) / IMAJEV_TEMPERATURE) for lt, lp in letter_lp.items()}
    tot = sum(exps.values())
    probs = {labels[lt]: round(v / tot, 4) for lt, v in exps.items()}

    if typ == "noul":
        nq = [probs.get("yes", 0.0), probs.get("no", 0.0)]
        tot = nq[0] + nq[1]
        nq = [p / tot for p in nq] if tot else [0.5, 0.5]
        return {"type": "noul",
                "probabilities": {"true": round(nq[0], 4), "false": round(nq[1], 4)},
                "confidence": round(_concentration(nq), 4)}
    if typ == "score":
        levels = sorted(probs, key=lambda k: float(k))
        return {"type": "score", "probabilities": probs,
                "score": sum(float(k) * probs[k] for k in levels)}
    best = max(probs, key=probs.get)
    conf = round(_concentration(list(probs.values())), 4)
    return {"type": "choice", "answer": best, "probabilities": probs,
            "confidence": conf}


def _health(url, timeout=3):
    """Is something already answering on this port?

    llama.cpp says `{"status": "ok"}`, the h2o shim says `{"ok": true}`. Both
    mean the slot is up; treating either as down would start a second candidate
    on a port that is already serving.
    """
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            if r.status not in (200, None):
                return False
            body = json.load(r)
            return body.get("status") == "ok" or body.get("ok") is True
    except Exception:  # noqa: BLE001 - "is it up" is the only question
        return False


def ask_jev(state, question, opts, typ):
    """Jev-Style-2B, in-process: no server, no port, no auto-start."""
    py = JEV_DIR / ".venv" / "bin" / "python"
    if not py.is_file():
        raise SystemExit(f"jev venv missing: {py}")
    cmd = [str(py), str(JEV_DIR / "jev_style_decision_gguf.py"),
           "--gguf", os.environ.get("JEV_GGUF") or _jev_default(),
           "--state", state, "--question", question,
           "--ngl", os.environ.get("JEV_NGL", "999"), "--threads", os.environ.get("JEV_THREADS", "8")]
    if opts is not None:
        cmd += ["--options", json.dumps(opts)]
        if typ in ("choice", "score"):
            cmd += ["--qtype", typ]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=900)
    if out.returncode != 0:
        raise SystemExit(out.stderr.strip()[:400] or "jev failed")
    try:
        return json.loads(out.stdout)          # jev prints one pretty-printed object
    except json.JSONDecodeError:
        raise SystemExit(f"unexpected jev output: {out.stdout.strip()[:300]}")


def _jev_default():
    return ("/run/media/rodri/AI/models/chaoliangUNSW/"
            "Jev-Style-Qwen3.5-2B-Decision-GGUF/Jev-Style-Qwen3.5-2B-Decision-Q4_K_M.gguf")


def flatten(qid, a):
    """llm2jev answer shape -> {answer, p, confidence}."""
    typ = a.get("type")
    probs = a.get("probabilities") or {}
    if typ is None:                                   # jev-style result: infer the type from the keys
        ks = list(probs)
        if set(ks) == {"true", "false"}:
            typ = "noul"
        elif ks and all(k.isdigit() for k in ks):
            typ = "score"
        else:
            typ = "choice"
    if typ == "noul":
        p_true = probs.get("true")
        answer = bool(p_true >= 0.5) if p_true is not None else a.get("answer")
    elif typ == "score":
        if "score" in a:
            answer = a["score"]
        else:
            answer = sum(float(k) * v for k, v in probs.items())
    else:
        answer = a.get("answer", max(probs, key=probs.__getitem__) if probs else None)
    conf = a.get("confidence")
    if conf is None:                                  # jev reports an entropy concentration instead
        conf = a.get("entropy_concentration", 0.0)
    return {"q": qid, "type": typ, "answer": answer,
            "p": {k: round(v, 4) for k, v in probs.items()},
            "confidence": round(conf, 4)}


def _norm_answer(answer, opts):
    """Map a model's answer onto the human label so different backends compare
    fairly. imajev/jev may return the criteria KEY ("0") rather than the LABEL
    ("trivial") - they are the same option but different strings."""
    s = str(answer)
    if isinstance(opts, (list, tuple)):
        # a positional key like "0" refers to opts[0]
        if s.lstrip("-").isdigit():
            i = int(s)
            if -len(opts) <= i < len(opts):
                return str(opts[i])
    return s


def _run_one(model, state, question, opts, typ, a):
    """Dispatch one model -> flattened {answer, p, confidence}. Shared by the
    primary run and by --cross-check so both go through identical code."""
    port = a.port
    if model in ("vllm", "d3"):
        port = VLLM_PORT if a.port is None else a.port
        ensure_vllm(port, a.timeout)
        raw = ask_vllm(state, question, opts, typ, port=port, timeout=a.timeout)
    elif model == "pplx":
        port = PPLX_PORT if a.port is None else a.port
        ensure_pplx(port, a.timeout)
        raw = ask_pplx(state, question, opts, typ, port=port, timeout=a.timeout)
    elif model in ("onejev", "imajev"):
        ensure_imajev(IMAJEV_PORT, a.timeout)
        port = IMAJEV_PORT if a.port is None else a.port
        raw = ask_imajev(state, question, opts, typ, port=port, timeout=a.timeout)
    elif model == "jev":
        raw = ask_jev(state, question, opts, typ)
    else:
        raise SystemExit(f"unknown model: {model}")
    return flatten("answer", raw)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("state_pos", nargs="?", help="the state to evaluate (text)")
    ap.add_argument("question_pos", nargs="?", help="the question")
    ap.add_argument("options_pos", nargs="?", help="JSON object (choice), JSON array (score), "
                                                  "comma list (score), or omit/none for noul")
    ap.add_argument("--state", help="same as the first positional")
    ap.add_argument("--question", help="same as the second positional")
    ap.add_argument("--options", help="same as the third positional")
    ap.add_argument("--model", default=os.environ.get("JEV_CLI_MODEL", "auto"),
                    choices=["auto", "vllm", "d3", "pplx", "onejev", "imajev", "jev"],
                    help="auto=pick the protocol from the model actually serving :8083 (default), "
                         "vllm=vllm-d3-mini native /v1/systemone on :8083, "
                         "d3=alias for vllm, "
                         "pplx=pplx-decider-flash v1.2 joint protocol v3 on :8083 (highest accuracy), "
                         "onejev=OneJev1.5-4B vision+decision fallback on :8089, "
                         "imajev=Imajev-4B alias on :8089, "
                         "jev=Jev-Style-2B run locally (no server, no port)")
    ap.add_argument("--state-file", help="read the state from a file")
    ap.add_argument("--type", default="auto", choices=["auto", "choice", "score", "noul"])
    ap.add_argument("--port", type=int, default=None,
                    help="model server port (default: vllm/pplx 8083, onejev/imajev 8089; "
                         "jev needs none)")
    ap.add_argument("--cross-check", metavar="MODEL[,MODEL...]", default=None,
                    help="run 2+ models on the same question and flag disagreement, "
                         "e.g. --cross-check imajev,vllm (implies the first as primary)")
    ap.add_argument("--batch", help="batch file: {\"state\":..., \"questions\": {qid: question}}")
    ap.add_argument("--threshold", type=float, default=0.5, help="noul answer cutoff")
    ap.add_argument("--raw", action="store_true", help="print the engine's full answer objects")
    ap.add_argument("--timeout", type=float, default=180, help="seconds to wait for the model to load")
    a = ap.parse_args()

    # ---- batch mode
    if a.batch:
        payload = json.loads(pathlib.Path(a.batch).read_text())
        if a.model in ("vllm", "d3"):
            port = VLLM_PORT if a.port is None else a.port
            ensure_vllm(port, a.timeout)
            answers = ask_vllm_batch(payload.get("state", ""), payload.get("questions") or {},
                                     port=port, timeout=a.timeout)
            print(json.dumps({"model": "vllm", "answers":
                              [flatten(q, answers[q]) for q in answers]}, indent=1))
            return
        raise SystemExit("batch mode supports --model vllm")

    state = pathlib.Path(a.state_file).read_text(errors="replace") if a.state_file \
        else (a.state or a.state_pos)
    question = a.question or a.question_pos
    options_arg = a.options if a.options is not None else a.options_pos
    if state is None or not question:
        ap.error("need: <state> <question> [options]  (or --state-file / --question / --batch)")

    # ---- typed question
    opts = None
    if options_arg and options_arg.strip() and options_arg.strip().lower() not in ("none", "-", "null"):
        raw = options_arg.strip()
        if raw.startswith("{"):
            opts = json.loads(raw)
        elif raw.startswith("["):
            opts = json.loads(raw)
        else:
            opts = [p.strip() for p in raw.split(",") if p.strip()]

    typ = a.type
    if typ == "auto":
        # A list is a *score* only if its levels are numeric - word labels like
        # ["trivial","serious","catastrophic"] are an ordered choice, and
        # float() on them raises deep inside the score maths.
        if not opts:
            typ = "noul"
        elif isinstance(opts, dict):
            typ = "choice"
        else:
            try:
                [float(x) for x in opts]
                typ = "score"
            except (TypeError, ValueError):
                typ = "choice"
    q = {"type": typ, "instructions": question}
    if typ == "choice":
        q["criteria"] = opts
    elif typ == "score":
        q["criteria"] = opts

    if a.port is None and a.model != "jev":
        a.port = {"auto": VLLM_PORT, "vllm": VLLM_PORT, "d3": VLLM_PORT,
                  "pplx": PPLX_PORT, "onejev": IMAJEV_PORT,
                  "imajev": IMAJEV_PORT}.get(a.model, VLLM_PORT)

    if a.model == "auto":
        served = _served_decision_type(a.port)
        a.model = "pplx" if served == "pplx-decider" else "vllm"

    if a.model in ("vllm", "d3"):
        ensure_vllm(a.port, a.timeout)
        ans = ask_vllm(state, question, opts, typ, port=a.port, timeout=a.timeout)
    elif a.model == "pplx":
        ensure_pplx(a.port, a.timeout)
        ans = ask_pplx(state, question, opts, typ, port=a.port, timeout=a.timeout)
    elif a.model in ("onejev", "imajev"):
        ensure_imajev(a.port, a.timeout)
        ans = ask_imajev(state, question, opts, typ, port=a.port, timeout=a.timeout)
    elif a.model == "jev":
        ans = ask_jev(state, question, opts, typ)
    else:
        raise SystemExit(f"unknown model: {a.model}")

    if a.raw:
        print(json.dumps(ans, indent=1))
        return
    f = flatten("answer", ans)
    if f["type"] == "noul":
        f["raw_p_true"] = round(f["p"].get("true", 0.0), 4)
        f["answer"] = bool(f["p"].get("true", 0.0) >= a.threshold)

    out = {"model": a.model, **f}

    if a.cross_check:
        models = [m.strip() for m in a.cross_check.split(",") if m.strip()]
        runs = {a.model: {"answer": f["answer"], "p": f["p"],
                          "confidence": f["confidence"],
                          "norm": _norm_answer(f["answer"], opts)}}
        for m in models:
            if m == a.model:
                continue
            try:
                sub = _run_one(m, state, question, opts, typ, a)
                runs[m] = {"answer": sub["answer"], "p": sub["p"],
                           "confidence": sub["confidence"],
                           "norm": _norm_answer(sub["answer"], opts)}
            except SystemExit as e:
                runs[m] = {"error": str(e)}
        answers = {m: r.get("norm") for m, r in runs.items() if "error" not in r}
        agree = len({str(v) for v in answers.values()}) == 1
        spread = None
        if f["type"] != "noul" and len(answers) > 1:
            vals = []
            for m, r in runs.items():
                if "error" in r:
                    continue
                v = r["p"].get(str(r["answer"]))
                if v is None:                       # keyed by label instead
                    v = r["p"].get(str(r["norm"]), 0.0)
                vals.append(v)
            spread = round(max(vals) - min(vals), 4) if vals else None
        out["cross_check"] = {"models": runs, "agree": agree,
                              "top_p_spread": spread}

    print(json.dumps(out))


if __name__ == "__main__":
    main()