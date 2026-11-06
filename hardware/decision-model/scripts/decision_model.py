#!/usr/bin/env python3
"""decision-model client — Calibrated Decision & Visual Grounding Model (h2o-lightning-4b).

Handles typed decisions (bool, choice, score) and visual bounding boxes (4 corners,
calibrated confidence, presence probability) on dual RX 9060 XT GPUs.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

DECISION_PORT = int(os.environ.get("DECISION_PORT", 8083))
BOX_PORT = int(os.environ.get("BOX_PORT", DECISION_PORT))
DEFAULT_HOST = os.environ.get("DECISION_HOST", "127.0.0.1")
SCORE_LEVELS = ["0.0", "0.25", "0.5", "0.75", "1.0"]
BOX_MIN_PRESENT = float(os.environ.get("BOX_MIN_PRESENT", 0.5))
BOX_MIN_CONFIDENCE = float(os.environ.get("BOX_MIN_CONFIDENCE", 0.30))
PROTOCOL_PRIMITIVES = ("bool", "choice", "score")


def box_capable(model_id: str) -> bool:
    """Box is a shim feature, not a protocol feature.

    llama.cpp's own `/v1/systemone` answers noul, choice and score. Only the
    h2oai shim implements the two-pass box readout (presence on the untouched
    image, tightness on the box-drawn one), so the capability is named by the
    served model rather than assumed from the port.
    """
    lowered = (model_id or "").lower()
    return "h2o" in lowered or "lightning" in lowered


def primitives(model_id: str) -> list[str]:
    caps = list(PROTOCOL_PRIMITIVES)
    if box_capable(model_id):
        caps.append("box")
    return caps


def gate_box(answer: dict, min_present: float = BOX_MIN_PRESENT,
             min_confidence: float = BOX_MIN_CONFIDENCE) -> tuple[bool, Optional[str]]:
    """The two failures are different, so they get two gates.

    `present` says the target exists at all; `confidence` says the box is
    tight. A missing target still returns `found: true` with a plausible
    rectangle, so `found` alone is not a decision.
    """
    present = float(answer.get("present", 0.0))
    confidence = float(answer.get("confidence", 0.0))
    if not answer.get("found", False):
        return False, "no box located"
    if present < min_present:
        return False, f"present {present:.3f} < {min_present:.3f}"
    if confidence < min_confidence:
        return False, f"confidence {confidence:.3f} < {min_confidence:.3f}"
    return True, None


def image_to_base64(path: Path) -> tuple[str, str]:
    blob = path.read_bytes()
    if blob[:8] == b"\x89PNG\r\n\x1a\n":
        fmt = "png"
    elif blob[:3] == b"\xff\xd8\xff":
        fmt = "jpg"
    else:
        fmt = "png"
    return fmt, base64.b64encode(blob).decode("ascii")

def served_model(port: int) -> str:
    """Name the model behind the slot; the slot rotates, the API does not."""
    url = f"http://{DEFAULT_HOST}:{port}/v1/models"
    try:
        with urllib.request.urlopen(url, timeout=3) as resp:
            models = json.loads(resp.read().decode("utf-8")).get("data") or []
    except Exception as exc:
        raise SystemExit(f"decision-model error: no decision server at {url} ({exc})")
    model_id = str(models[0].get("id", "")) if models and isinstance(models[0], dict) else ""
    if not model_id:
        raise SystemExit(f"decision-model error: no model named at {url}")
    if os.environ.get("DECISION_REQUIRE_H2O") == "1" and "h2o-lightning-4b" not in model_id.lower():
        raise SystemExit(f"decision-model error: expected h2o-lightning-4b at {url}; got {model_id}")
    return model_id

def post_systemone(payload: dict, port: int = DECISION_PORT, timeout: float = 30.0) -> dict:
    served_model(port)
    url = f"http://{DEFAULT_HOST}:{port}/v1/systemone"
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")[:400]
        raise SystemExit(f"decision-model error: HTTP {e.code} from {url} — {detail}")
    except urllib.error.URLError as e:
        raise SystemExit(f"decision-model error: could not connect to {url} ({e.reason}). Start with sh/h2o.sh")

def cmd_bool(context: str, question: str, image: Optional[Path] = None, json_mode: bool = False) -> int:
    payload: Dict[str, Any] = {
        "state": {"context": context},
        "questions": {"q": {"type": "noul", "instructions": question}},
    }
    if image and image.is_file():
        fmt, b64 = image_to_base64(image)
        payload["assets"] = {"img": {"type": "image", "format": fmt, "data_base64": b64}}
        payload["questions"]["q"]["image"] = "img"

    res = post_systemone(payload)
    ans = res.get("answers", {}).get("q", {})
    prob = ans.get("noul", ans.get("probability", ans.get("probabilities", {}).get("true", 0.0)))
    if json_mode:
        print(json.dumps({
            "primitive": "bool",
            "decision": bool(prob >= 0.5),
            "probability": prob,
            "question": question,
        }, indent=2))
    else:
        print(f"Decision: {'YES' if prob >= 0.5 else 'NO'} | P(true) = {prob:.4f}")
    return 0 if prob >= 0.5 else 1

def cmd_choice(context: str, question: str, options: List[str], image: Optional[Path] = None, json_mode: bool = False) -> int:
    payload: Dict[str, Any] = {
        "state": {"context": context},
        "questions": {"q": {
            "type": "choice",
            "instructions": question,
            "criteria": {opt: opt for opt in options},
        }},
    }
    if image and image.is_file():
        fmt, b64 = image_to_base64(image)
        payload["assets"] = {"img": {"type": "image", "format": fmt, "data_base64": b64}}
        payload["questions"]["q"]["image"] = "img"

    res = post_systemone(payload)
    ans = res.get("answers", {}).get("q", {})
    choice = ans.get("choice", ans.get("selection", ""))
    probs = ans.get("probabilities", {})
    if json_mode:
        print(json.dumps({
            "primitive": "choice",
            "selection": choice,
            "probabilities": probs,
            "question": question,
        }, indent=2))
    else:
        print(f"Selection: {choice}")
        for opt, p in probs.items():
            print(f"  - {opt:20}: {p:.4f}")
    return 0

def cmd_score(context: str, criteria: str, levels: List[str], image: Optional[Path] = None, json_mode: bool = False) -> int:
    payload: Dict[str, Any] = {
        "state": {"context": context},
        "questions": {"q": {"type": "score", "instructions": criteria, "criteria": levels}},
    }
    if image and image.is_file():
        fmt, b64 = image_to_base64(image)
        payload["assets"] = {"img": {"type": "image", "format": fmt, "data_base64": b64}}
        payload["questions"]["q"]["image"] = "img"

    res = post_systemone(payload)
    ans = res.get("answers", {}).get("q", {})
    index = float(ans.get("score", 0.0))
    scalar = index / (len(levels) - 1) if len(levels) > 1 else 0.0
    if json_mode:
        print(json.dumps({
            "primitive": "score",
            "score": min(1.0, max(0.0, scalar)),
            "level": index,
            "levels_count": len(levels),
            "criteria": criteria,
        }, indent=2))
    else:
        print(f"Score: {min(1.0, max(0.0, scalar)):.4f} / 1.0000  (level {index:.2f} of {len(levels) - 1})")
    return 0

def cmd_box(image: Path, target: str, crop_out: Optional[Path] = None, json_mode: bool = False,
            min_present: float = BOX_MIN_PRESENT,
            min_confidence: float = BOX_MIN_CONFIDENCE,
            timeout: float = 120.0) -> int:
    model = served_model(BOX_PORT)
    if not box_capable(model):
        raise SystemExit(
            f"decision-model error: :{BOX_PORT} serves {model}, which has no box primitive. "
            f"Box answers come from the h2oai shim — start it with `h2o.sh` (slot :8083), "
            f"or point BOX_PORT at a running standalone shim (:8761)."
        )

    fmt, b64 = image_to_base64(image)
    ref = "photo"
    payload = {
        "state": {"note": "box request"},
        "questions": {"loc": {"type": "box", "instructions": f"{target} in `{ref}`"}},
        "assets": {ref: {"type": "image", "format": fmt, "data_base64": b64}},
    }
    res = post_systemone(payload, port=BOX_PORT, timeout=timeout)
    ans = res.get("answers", {}).get("loc", {})
    box = ans.get("box", {})
    accepted, reason = gate_box(ans, min_present, min_confidence)

    pixels = None
    try:
        from PIL import Image
        with Image.open(image) as src:
            w, h = src.size
        pixels = {
            "left": round(box.get("left", 0.0) * w),
            "top": round(box.get("top", 0.0) * h),
            "right": round(box.get("right", 0.0) * w),
            "bottom": round(box.get("bottom", 0.0) * h),
            "width": w,
            "height": h,
        }
    except ImportError:
        pass

    cropped = None
    if accepted and crop_out:
        try:
            from PIL import Image
            with Image.open(image) as src:
                w, h = src.size
                pix = (
                    max(0, round(box["left"] * w)),
                    max(0, round(box["top"] * h)),
                    min(w, round(box["right"] * w)),
                    min(h, round(box["bottom"] * h)),
                )
                src.crop(pix).save(crop_out)
                cropped = f"{pix[2]-pix[0]}x{pix[3]-pix[1]} px"
        except ImportError:
            cropped = "skipped: Pillow not installed"

    if json_mode:
        print(json.dumps({
            "target": target,
            "image": str(image),
            "model": model,
            "accepted": accepted,
            "reason": reason,
            "box": box,
            "pixels": pixels,
            "confidence": ans.get("confidence", 0.0),
            "present": ans.get("present", 0.0),
            "found": bool(ans.get("found", False)),
            "crop": str(crop_out) if cropped and not cropped.startswith("skipped") else None,
            "crop_note": cropped,
        }, indent=2))
        return 0 if accepted else 2

    if accepted:
        print(f"ACCEPT  box=({box.get('left',0):.3f}, {box.get('top',0):.3f}) -> "
              f"({box.get('right',0):.3f}, {box.get('bottom',0):.3f})  "
              f"confidence={ans.get('confidence',0):.3f}  present={ans.get('present',0):.3f}")
        if cropped:
            print(f"Crop saved to {crop_out} ({cropped})" if crop_out else f"Crop {cropped}")
    else:
        print(f"REJECT  {reason}  present={ans.get('present',0):.3f}  "
              f"confidence={ans.get('confidence',0):.3f}")

    return 0 if accepted else 2


def cmd_caps(json_mode: bool = False) -> int:
    model = served_model(DECISION_PORT)
    caps = primitives(model)
    payload = {
        "model": model,
        "slot": DECISION_PORT,
        "box_port": BOX_PORT,
        "primitives": caps,
        "vision": "box" in caps,
        "note": None if "box" in caps else (
            "box needs the h2oai shim; this endpoint answers noul, choice and score only"
        ),
    }
    if json_mode:
        print(json.dumps(payload, indent=2))
    else:
        print(f"model       {model}")
        print(f"slot        :{DECISION_PORT}  (box on :{BOX_PORT})")
        print(f"primitives  {', '.join(caps)}")
        if payload["note"]:
            print(f"note        {payload['note']}")
    return 0


def cmd_doctor(json_mode: bool = False) -> int:
    model = ""
    try:
        model = served_model(DECISION_PORT)
    except Exception:
        pass

    box_up = False
    try:
        urllib.request.urlopen(f"http://{DEFAULT_HOST}:{BOX_PORT}/health", timeout=2)
        box_up = True
    except Exception:
        pass

    online = bool(model or box_up)
    if json_mode:
        print(json.dumps({
            "decision_port": DECISION_PORT,
            "decision_online": bool(model),
            "model": model or None,
            "box_port": BOX_PORT,
            "box_online": box_up,
            "status": "online" if online else "offline",
        }, indent=2))
    else:
        print("🩺 Checking Decision Model endpoints...")
        print(f"  :{DECISION_PORT} (Native /v1/systemone): {'🟢 ONLINE' if model else '⚪ OFFLINE'}"
              + (f" — {model}" if model else ""))
        where = "same port" if BOX_PORT == DECISION_PORT else f":{BOX_PORT}"
        print(f"  :{BOX_PORT} (Visual Box Shim, {where})       : {'🟢 ONLINE' if box_up else '⚪ OFFLINE'}")
    return 0 if online else 1

def main() -> int:
    p = argparse.ArgumentParser(description="decision-model: h2o-lightning-4b Decision & Visual Grounding Client")
    sub = p.add_subparsers(dest="cmd", required=True)

    b_p = sub.add_parser("bool", help="Binary decision")
    b_p.add_argument("--context", required=True, help="Background context")
    b_p.add_argument("--question", required=True, help="Question to judge")
    b_p.add_argument("--image", type=Path, help="Optional image path")
    b_p.add_argument("--json", action="store_true", help="JSON output")

    c_p = sub.add_parser("choice", help="Constrained categorical choice")
    c_p.add_argument("--context", required=True, help="Background context")
    c_p.add_argument("--question", required=True, help="Question to classify")
    c_p.add_argument("--options", nargs="+", required=True, help="Allowed choices")
    c_p.add_argument("--image", type=Path, help="Optional image path")
    c_p.add_argument("--json", action="store_true", help="JSON output")

    s_p = sub.add_parser("score", help="Scalar score on [0, 1]")
    s_p.add_argument("--context", required=True, help="Background context")
    s_p.add_argument("--criteria", required=True, help="Scoring criteria")
    s_p.add_argument("--levels", nargs="+", default=SCORE_LEVELS,
                     help="Ordered levels the score is read over (default: 0.0 0.25 0.5 0.75 1.0)")
    s_p.add_argument("--image", type=Path, help="Optional image path")
    s_p.add_argument("--json", action="store_true", help="JSON output")

    box_p = sub.add_parser("box", help="Visual bounding box localization")
    box_p.add_argument("--image", type=Path, required=True, help="Image path")
    box_p.add_argument("--target", required=True, help="Object or phrase to locate")
    box_p.add_argument("--crop", type=Path, help="Save cropped region")
    box_p.add_argument("--min-present", type=float, default=BOX_MIN_PRESENT, metavar="SCORE",
                       help="Reject below this presence probability (default 0.5)")
    box_p.add_argument("--min-confidence", type=float, default=BOX_MIN_CONFIDENCE, metavar="SCORE",
                       help="Reject below this tightness confidence (default 0.30)")
    box_p.add_argument("--timeout", type=float, default=120.0, metavar="TIMEOUT")
    box_p.add_argument("--json", action="store_true", help="JSON output")

    caps_p = sub.add_parser("caps", help="What the served model can answer")
    caps_p.add_argument("--json", action="store_true", help="JSON output")

    doc_p = sub.add_parser("doctor", help="Check server health")
    doc_p.add_argument("--json", action="store_true", help="JSON output")

    args = p.parse_args()
    if args.cmd == "bool":
        return cmd_bool(args.context, args.question, args.image, json_mode=args.json)
    elif args.cmd == "choice":
        return cmd_choice(args.context, args.question, args.options, args.image, json_mode=args.json)
    elif args.cmd == "score":
        return cmd_score(args.context, args.criteria, args.levels, args.image, json_mode=args.json)
    elif args.cmd == "box":
        return cmd_box(args.image, args.target, args.crop, args.json,
                       args.min_present, args.min_confidence, args.timeout)
    elif args.cmd == "caps":
        return cmd_caps(args.json)
    elif args.cmd == "doctor":
        return cmd_doctor(json_mode=args.json)
    return 1

if __name__ == "__main__":
    sys.exit(main())
