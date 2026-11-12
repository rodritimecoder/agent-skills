#!/usr/bin/env python3
"""decision-model client — Calibrated Decision & Visual Grounding engine.

Handles typed decisions (bool, choice, score) and visual bounding boxes (4 corners,
calibrated confidence, presence probability) on the decision slot (:8083).

The slot rotates between backends; the client adapts its request shape to the
served architecture. h2o-lightning-4b runs behind the h2oai shim (state.context +
assets, two-pass box readout). Valen-Decision-1.5 runs on its own custom llama.cpp
runtime (messages with inline data URLs, single-pass bbox answer).
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


def is_valen(model_id: str) -> bool:
    return "valen" in (model_id or "").lower()


def box_capable(model_id: str) -> bool:
    """Box is a per-backend feature, not a protocol feature.

    llama.cpp's own `/v1/systemone` answers noul, choice and score. h2o-lightning
    adds a two-pass box readout in the h2oai shim (presence on the untouched
    image, tightness on the box-drawn one). Valen-Decision-1.5 has a bbox
    grounding head in the model itself and returns a box in the same pass. Match
    the served model, not the port.
    """
    lowered = (model_id or "").lower()
    return "h2o" in lowered or "lightning" in lowered or "valen" in lowered


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
    rectangle, so `found` alone is not a decision. Valen's bbox head reports no
    separate presence probability, so `present` may be None and only the
    confidence gate applies.
    """
    present = answer.get("present")
    confidence = float(answer.get("confidence", 0.0))
    if not answer.get("found", False):
        return False, "no box located"
    if present is not None and float(present) < min_present:
        return False, f"present {float(present):.3f} < {min_present:.3f}"
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


def image_data_url(path: Path) -> str:
    fmt, b64 = image_to_base64(path)
    return f"data:image/{fmt};base64,{b64}"


def build_payload(context: str, question: Dict[str, Any], image: Optional[Path] = None,
                  port: int = DECISION_PORT) -> dict:
    """Shape one request for whichever backend holds the slot.

    h2o reads `state.context` and a named `assets` map. Valen reads
    `state.messages` and expects images inline as data URLs, because the model
    evaluates state and questions in one shared pass.
    """
    model = served_model(port)
    if is_valen(model):
        content: List[Dict[str, Any]] = []
        if image and image.is_file():
            content.append({"type": "image_url", "image_url": {"url": image_data_url(image)}})
        if context:
            content.append({"type": "text", "text": context})
        return {
            "state": {"messages": [{"role": "user", "content": content}]},
            "questions": {"q": question},
        }

    payload: Dict[str, Any] = {"state": {"context": context}, "questions": {"q": question}}
    if image and image.is_file():
        fmt, b64 = image_to_base64(image)
        payload["assets"] = {"img": {"type": "image", "format": fmt, "data_base64": b64}}
        payload["questions"]["q"]["image"] = "img"
    return payload


def normalize_box_answer(ans: dict) -> dict:
    """Flatten both box answer shapes into one gated result.

    h2o: `box {left,top,right,bottom}` + `present` + `confidence` + `found`.
    Valen: `bbox [x1,y1,x2,y2]` + `point` + `confidence`, no presence head.
    """
    bbox = ans.get("bbox")
    if isinstance(bbox, list) and len(bbox) == 4:
        left, top, right, bottom = (float(v) for v in bbox)
        return {
            "box": {"left": left, "top": top, "right": right, "bottom": bottom},
            "present": ans.get("present"),
            "confidence": float(ans.get("confidence", 0.0)),
            "found": True,
            "point": ans.get("point"),
        }
    box = ans.get("box", {})
    return {
        "box": box,
        "present": ans.get("present", 0.0),
        "confidence": float(ans.get("confidence", 0.0)),
        "found": bool(ans.get("found", False)) and bool(box),
        "point": ans.get("point"),
    }

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
        raise SystemExit(f"decision-model error: could not connect to {url} ({e.reason}). Start with sh/h2o.sh or sh/valen.sh")

def cmd_bool(context: str, question: str, image: Optional[Path] = None, json_mode: bool = False) -> int:
    payload = build_payload(context, {"type": "noul", "instructions": question}, image)

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
    payload = build_payload(context, {
        "type": "choice",
        "instructions": question,
        "criteria": {opt: opt for opt in options},
    }, image)

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
    payload = build_payload(context, {"type": "score", "instructions": criteria, "criteria": levels}, image)

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
            f"Box answers come from h2o-lightning (h2o.sh) or Valen-Decision-1.5 (valen.sh) "
            f"on slot :8083, or point BOX_PORT at a running standalone h2oai shim (:8761)."
        )

    if is_valen(model):
        payload = {
            "state": {"messages": [{"role": "user", "content": [
                {"type": "image_url", "image_url": {"url": image_data_url(image)}},
            ]}]},
            "questions": {"loc": {"type": "bbox", "instructions": target, "image": 0}},
        }
    else:
        fmt, b64 = image_to_base64(image)
        ref = "photo"
        payload = {
            "state": {"note": "box request"},
            "questions": {"loc": {"type": "box", "instructions": f"{target} in `{ref}`"}},
            "assets": {ref: {"type": "image", "format": fmt, "data_base64": b64}},
        }
    res = post_systemone(payload, port=BOX_PORT, timeout=timeout)
    ans = normalize_box_answer(res.get("answers", {}).get("loc", {}))
    box = ans["box"]
    present = ans.get("present")
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
            "confidence": ans["confidence"],
            "present": present,
            "found": bool(ans["found"]),
            "point": ans.get("point"),
            "crop": str(crop_out) if cropped and not cropped.startswith("skipped") else None,
            "crop_note": cropped,
        }, indent=2))
        return 0 if accepted else 2

    present_note = "n/a" if present is None else f"{float(present):.3f}"
    if accepted:
        print(f"ACCEPT  box=({box.get('left',0):.3f}, {box.get('top',0):.3f}) -> "
              f"({box.get('right',0):.3f}, {box.get('bottom',0):.3f})  "
              f"confidence={ans['confidence']:.3f}  present={present_note}")
        if cropped:
            print(f"Crop saved to {crop_out} ({cropped})" if crop_out else f"Crop {cropped}")
    else:
        print(f"REJECT  {reason}  present={present_note}  "
              f"confidence={ans['confidence']:.3f}")

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
            "box needs h2o-lightning (h2o.sh) or Valen-Decision-1.5 (valen.sh); "
            "this endpoint answers noul, choice and score only"
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
