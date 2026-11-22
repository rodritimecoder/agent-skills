#!/usr/bin/env python3
"""Catalog reconciliation for the openrouter-free skill.

Discovers genuinely free OpenRouter endpoints, classifies them into roles,
and reconciles them into catalog.json. No live chat/completion inference is
performed unless --probe is explicitly passed with credentials.
"""

import argparse
import copy
import json
import math
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CATALOG_URL = "https://openrouter.ai/api/v1/models?output_modalities=all"
ROLES = ("chat", "decide", "embed", "rerank", "tts")
SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = SKILL_ROOT / "catalog.json"

DECISION_ENDPOINT = "/api/alpha/decisions"
EMBED_ENDPOINT = "/api/v1/embeddings"
TTS_ENDPOINT = "/api/v1/audio/speech"
CHAT_ENDPOINT = "/api/v1/chat/completions"
DECIDE_NAME_TOKENS = ("decide", "jev", "mercury", "mammoth", "elephant", "respan")


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(path=None):
    if path is None:
        path = os.environ.get("CATALOG_PATH", "").strip() or DEFAULT_CATALOG_PATH
    return Path(path).expanduser()


def empty_manifest():
    return {
        "schema_version": 1,
        "source": CATALOG_URL,
        "updated_at": "",
        "roles": {role: [] for role in ROLES},
        "models": {},
        "candidates": [],
        "retired": [],
    }


def _normalize_manifest(m):
    result = dict(m or {})
    for key, value in empty_manifest().items():
        result.setdefault(key, value)
    roles = result.get("roles") if isinstance(result.get("roles"), dict) else {}
    result["roles"] = {role: list(roles.get(role, [])) for role in ROLES}
    if not isinstance(result.get("models"), dict):
        result["models"] = {}
    if not isinstance(result.get("candidates"), list):
        result["candidates"] = []
    if not isinstance(result.get("retired"), list):
        result["retired"] = []
    return result


def load_manifest(path=None):
    """Read the manifest, returning an empty skeleton when the file is absent."""
    target = _resolve_path(path)
    if not target.is_file():
        return empty_manifest()
    data = json.loads(target.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("catalog manifest root must be a JSON object")
    return _normalize_manifest(data)


def save_manifest(m, path=None):
    """Atomically write the manifest via a same-directory temp file + os.replace."""
    target = _resolve_path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".catalog-", suffix=".tmp", dir=str(target.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(_normalize_manifest(m), handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def is_zero_cost(model):
    """True only when both prompt and completion are exactly 0 (not -1/NaN/missing)."""
    if not isinstance(model, dict):
        return False
    pricing = model.get("pricing")
    if not isinstance(pricing, dict):
        return False
    prompt = pricing.get("prompt")
    completion = pricing.get("completion")
    if prompt is None or completion is None:
        return False
    try:
        p = float(prompt)
        c = float(completion)
    except (TypeError, ValueError):
        return False
    if math.isnan(p) or math.isnan(c) or math.isinf(p) or math.isinf(c):
        return False
    if p < 0 or c < 0:  # -1 is OpenRouter's dynamic-router sentinel
        return False
    return p == 0.0 and c == 0.0


def _endpoints(model):
    raw = model.get("supported_endpoints") or model.get("endpoints") or []
    if isinstance(raw, str):
        raw = [raw]
    return {str(item).lower() for item in raw}


def _output_modalities(model):
    arch = model.get("architecture") or {}
    raw = arch.get("output_modalities") or model.get("output_modalities") or []
    if isinstance(raw, str):
        raw = [raw]
    return {str(item).lower() for item in raw}


def _supports_tools(model):
    raw = model.get("supported_parameters") or []
    if isinstance(raw, str):
        raw = [raw]
    params = {str(item).lower() for item in raw}
    if "tools" in params or "tool_choice" in params:
        return True
    return model.get("tools") is True or model.get("tool_support") is True


def classify(model):
    """Assign one role, or None when no role is unambiguous.

    Ordered by specificity: audio/embed/rerank/decide signals outrank the
    generic chat endpoint, which additionally requires text output + tools.
    """
    if not isinstance(model, dict):
        return None
    endpoints = _endpoints(model)
    outputs = _output_modalities(model)
    name = str(model.get("name") or model.get("id") or "").lower()
    ident = str(model.get("id") or "").lower()
    label = name + " " + ident

    if any(mod in ("speech", "audio") for mod in outputs) or any(
        TTS_ENDPOINT in ep for ep in endpoints
    ):
        return "tts"
    if any(EMBED_ENDPOINT in ep for ep in endpoints) or "embed" in label:
        return "embed"
    if "rerank" in label or any("rerank" in ep for ep in endpoints):
        return "rerank"
    if any(DECISION_ENDPOINT in ep for ep in endpoints) or any(
        token in label for token in DECIDE_NAME_TOKENS
    ):
        return "decide"
    if CHAT_ENDPOINT in endpoints and "text" in outputs and _supports_tools(model):
        return "chat"
    return None


def fetch_catalog(url=CATALOG_URL, fixture=None):
    """Return a list of model dicts from the public endpoint or an offline fixture."""
    if fixture is not None:
        if isinstance(fixture, (str, Path)):
            data = json.loads(Path(fixture).read_text(encoding="utf-8"))
        elif isinstance(fixture, (list, dict)):
            data = fixture
        else:
            raise ValueError("fixture must be a path or decoded JSON list/object")
    else:
        request = urllib.request.Request(url)
        key = os.environ.get("OPENROUTER_API_KEY", "").strip()
        if key:
            request.add_header("Authorization", f"Bearer {key}")
        with urllib.request.urlopen(request, timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    if isinstance(data, dict):
        return list(data.get("data", []))
    if isinstance(data, list):
        return data
    raise ValueError("catalog payload must be a list or an object with a 'data' list")


def _model_meta(model, role):
    arch = model.get("architecture") or {}
    inputs = arch.get("input_modalities") or model.get("input_modalities") or []
    outputs = arch.get("output_modalities") or model.get("output_modalities") or []
    try:
        context = int(model.get("context_length") or 0)
    except (TypeError, ValueError):
        context = 0
    return {
        "role": role,
        "name": str(model.get("name") or model.get("id") or ""),
        "context_length": context,
        "input_modalities": [str(item) for item in inputs],
        "output_modalities": [str(item) for item in outputs],
    }


def _probe_failed(probe_results, model_id):
    if not isinstance(probe_results, dict):
        return False
    entry = probe_results.get(model_id)
    return isinstance(entry, dict) and entry.get("ok") is False


def build_plan(current, catalog, probe=None):
    """Diff active roles against a fresh catalog; return {manifest, report}.

    Delisted, priced, and probe-failed ids are moved to retired with a reason;
    free-but-unclassified ids go to candidates. Retired ids that are alive,
    free and classifiable again are re-activated into their role. Nothing is
    hard-deleted: retired history is retained with a ``reactivated_at`` marker.
    """
    plan = _normalize_manifest(copy.deepcopy(current))
    by_id = {
        model["id"]: model
        for model in (catalog or [])
        if isinstance(model, dict) and model.get("id")
    }
    now = _iso_now()
    retired_ids = {
        entry.get("id")
        for entry in plan["retired"]
        if isinstance(entry, dict) and entry.get("id")
    }
    active_ids = set()
    added = []
    retired_now = []
    reactivated = []

    for role in ROLES:
        survivors = []
        for model_id in plan["roles"][role]:
            model = by_id.get(model_id)
            reason = None
            if model is None:
                reason = "delisted"
            elif not is_zero_cost(model):
                reason = "priced"
            elif _probe_failed(probe, model_id):
                reason = "probe_failed"
            if reason is not None:
                if model_id not in retired_ids:
                    plan["retired"].append(
                        {"id": model_id, "role": role, "reason": reason, "since": now}
                    )
                    retired_ids.add(model_id)
                    retired_now.append(model_id)
                plan["models"].pop(model_id, None)
                continue
            survivors.append(model_id)
            active_ids.add(model_id)
            plan["models"][model_id] = _model_meta(model, role)
        plan["roles"][role] = survivors

    # Re-activation: a retired id that is present in the fresh catalog, still
    # zero-cost and classifiable returns to its role. The retired history entry
    # is kept (never hard-deleted) and tagged with a reactivated_at timestamp.
    for entry in plan["retired"]:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not model_id:
            continue
        model = by_id.get(model_id)
        if model is None or not is_zero_cost(model):
            continue
        role = classify(model)
        if role is None:
            continue
        if model_id in active_ids:  # never duplicate across roles
            continue
        if _probe_failed(probe, model_id):  # keep retired while probe still fails
            continue
        plan["roles"][role].append(model_id)
        plan["models"][model_id] = _model_meta(model, role)
        active_ids.add(model_id)
        entry["reactivated_at"] = now
        reactivated.append(model_id)

    candidates = []
    for model in catalog or []:
        if not isinstance(model, dict) or not model.get("id"):
            continue
        model_id = model["id"]
        if not is_zero_cost(model):
            continue
        role = classify(model)
        if role is None:
            if model_id not in candidates:
                candidates.append(model_id)
            continue
        if model_id in retired_ids or model_id in active_ids:
            continue
        if _probe_failed(probe, model_id):
            plan["retired"].append(
                {"id": model_id, "role": role, "reason": "probe_failed", "since": now}
            )
            retired_ids.add(model_id)
            retired_now.append(model_id)
            continue
        plan["roles"][role].append(model_id)
        plan["models"][model_id] = _model_meta(model, role)
        active_ids.add(model_id)
        added.append(model_id)

    plan["candidates"] = candidates
    plan["updated_at"] = now
    plan["source"] = plan.get("source") or CATALOG_URL
    plan["schema_version"] = 1

    report = {
        "drift": bool(added or retired_now or reactivated),
        "added": added,
        "retired": retired_now,
        "reactivated": reactivated,
        "candidates": candidates,
        "checked_at": now,
        "source": plan["source"],
    }
    return {"manifest": plan, "report": report}


def _probe_one(model_id, role, api_key, timeout):
    if role in ("embed",):
        url = "https://openrouter.ai/api/v1/embeddings"
        payload = {"model": model_id, "input": "ping"}
    elif role == "tts":
        url = "https://openrouter.ai/api/v1/audio/speech"
        payload = {"model": model_id, "input": "ping", "voice": "alloy"}
    elif role == "decide":
        url = "https://openrouter.ai" + DECISION_ENDPOINT
        payload = {
            "model": model_id,
            "state": "ping",
            "questions": {
                "probe": {
                    "type": "noul",
                    "instructions": "Is this a connectivity probe?",
                    "criteria": {"true": "yes", "false": "no"},
                }
            },
        }
    else:
        url = "https://openrouter.ai" + CHAT_ENDPOINT
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 1,
        }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response.read(1)
        return {"ok": True, "error": ""}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def probe(manifest, timeout=5.0):
    """Opt-in live reachability check; never called implicitly."""
    results = {}
    api_key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        for role in ROLES:
            for model_id in manifest.get("roles", {}).get(role, []):
                results[model_id] = {
                    "ok": False,
                    "error": "OPENROUTER_API_KEY not configured",
                }
        return results
    for role in ROLES:
        for model_id in manifest.get("roles", {}).get(role, []):
            results[model_id] = _probe_one(model_id, role, api_key, timeout)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="catalog_sync.py",
        description="Reconcile the openrouter-free free-model catalog manifest.",
        epilog="Exit codes: 0 success; 1 runtime error or drift; 2 usage error.",
    )
    parser.add_argument("--check", action="store_true", help="read-only drift check")
    parser.add_argument("--apply", action="store_true", help="write the reconciled manifest")
    parser.add_argument(
        "--probe", action="store_true",
        help="opt-in live endpoint probe (requires OPENROUTER_API_KEY)",
    )
    parser.add_argument("--json", action="store_true", help="emit the JSON report to stdout")
    parser.add_argument(
        "--fixture", metavar="PATH", default=None,
        help="offline catalog JSON to use instead of the live endpoint",
    )
    args = parser.parse_args(argv)

    if args.check == args.apply:
        sys.stderr.write("usage: choose exactly one of --check or --apply\n")
        return 2
    if args.probe and not os.environ.get("OPENROUTER_API_KEY", "").strip():
        sys.stderr.write("usage: --probe requires OPENROUTER_API_KEY\n")
        return 2

    try:
        catalog = fetch_catalog(fixture=args.fixture)
        current = load_manifest()
        probe_results = probe(current) if args.probe else None
        outcome = build_plan(current, catalog, probe=probe_results)
        report = outcome["report"]
        if args.apply:
            save_manifest(outcome["manifest"])
        if args.json:
            print(json.dumps(report, indent=2))
        else:
            sys.stderr.write(
                "[catalog_sync] %s: drift=%s added=%s retired=%s reactivated=%d "
                "candidates=%s\n"
                % (
                    "applied" if args.apply else "checked",
                    report["drift"],
                    ",".join(report["added"]) or "-",
                    ",".join(report["retired"]) or "-",
                    len(report["reactivated"]),
                    len(report["candidates"]),
                )
            )
        if args.check and report["drift"]:
            return 1
        return 0
    except Exception as exc:
        sys.stderr.write(f"[catalog_sync] {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
