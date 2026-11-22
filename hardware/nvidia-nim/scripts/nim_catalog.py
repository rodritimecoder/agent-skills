#!/usr/bin/env python3
"""Catalog reconciliation for the nvidia-nim skill.

NVIDIA's public /v1/models endpoint is keyless, but returns ONLY
id/object/created/owned_by -- no pricing, context, modality or capability data.
Eligibility here therefore means exactly one thing: present in the live catalog.
Nothing in this module infers or asserts that a model is free.

Live inference (``--probe``) is strictly opt-in and requires NVIDIA_API_KEY;
it spends quota. Everything else is read-only against the public catalog.
"""

import argparse
import copy
import json
import os
import sys
import tempfile
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

CATALOG_URL = "https://integrate.api.nvidia.com/v1/models"
DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
SCHEMA_VERSION = 1
ROLES = ("chat", "embed", "decide")

SKILL_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CATALOG_PATH = SKILL_ROOT / "catalog.json"
CATALOG_PATH_ENV = "NIM_CATALOG_PATH"
API_KEY_ENV = "NVIDIA_API_KEY"

# Name-based hints. Embed tokens are unambiguous enough to classify on their
# own; decide tokens are NOT (a name is a guess) and need a successful probe.
EMBED_NAME_TOKENS = ("embed", "retriever", "nvclip")
DECIDE_NAME_TOKENS = ("decide", "jev", "mercury")
CHAT_FAMILY_TOKENS = (
    "glm", "deepseek", "llama", "nemotron", "qwen", "gpt", "mistral",
    "mixtral", "gemma", "phi", "claude", "command", "jamba", "kimi",
    "minimax", "vicuna", "falcon", "yi-", "starcoder", "codellama",
)

# Specialist / sensitive ids stay in the candidate pool even when their name
# carries a chat family token. Name-only promotion is deliberately conservative:
# guardrails, safety, detection, calibration, translation, PII and code models
# are not general-purpose chat models.
NEGATIVE_ID_TOKENS = (
    "guard", "safety", "moderation", "detector", "content-safety",
    "bolt", "calibration", "translate", "pii", "video-detector",
    "starcoder",
    # "omni" marks the multimodal Nemotron specialist; without it the
    # "nemotron" family token alone promotes that id into chat.
    "omni",
)


def _iso_now():
    return datetime.now(timezone.utc).isoformat()


def _resolve_path(path=None):
    if path is None:
        path = os.environ.get(CATALOG_PATH_ENV, "").strip() or DEFAULT_CATALOG_PATH
    return Path(path).expanduser()


def empty_manifest():
    return {
        "schema_version": SCHEMA_VERSION,
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
    retired = result.get("retired") if isinstance(result.get("retired"), list) else []
    normalized_retired = []
    for entry in retired:
        if not isinstance(entry, dict):
            continue
        entry.setdefault("reactivated_at", None)
        normalized_retired.append(entry)
    result["retired"] = normalized_retired
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
    fd, tmp = tempfile.mkstemp(prefix=".nim-catalog-", suffix=".tmp", dir=str(target.parent))
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


def fetch_catalog(url=CATALOG_URL, fixture=None):
    """Return the public model list, or decoded offline fixture data.

    A fixture may be a path (str/Path), a decoded list/object, or a JSON string.
    No credential is needed for the live catalog fetch.
    """
    if fixture is not None:
        if isinstance(fixture, (str, Path)):
            text = str(fixture)
            if text.lstrip()[:1] in ("[", "{"):
                data = json.loads(text)
            else:
                data = json.loads(Path(fixture).read_text(encoding="utf-8"))
        elif isinstance(fixture, (list, dict)):
            data = fixture
        else:
            raise ValueError("fixture must be a path, JSON string, or decoded list/object")
    else:
        with urllib.request.urlopen(urllib.request.Request(url), timeout=30) as response:
            data = json.loads(response.read().decode("utf-8"))
    if isinstance(data, dict):
        return list(data.get("data", []))
    if isinstance(data, list):
        return data
    raise ValueError("catalog payload must be a list or an object with a 'data' list")


def _model_meta(model, role):
    try:
        created = int(model.get("created") or 0)
    except (TypeError, ValueError):
        created = 0
    return {
        "role": role,
        "name": str(model.get("name") or model.get("id") or ""),
        "created": created,
        "owned_by": str(model.get("owned_by") or ""),
    }


def _as_probe_result(value, model_id=None):
    """Normalize a probe input into a single {"ok": bool, "error": str} entry."""
    if value is None:
        return None
    if isinstance(value, bool):
        return {"ok": value, "error": ""}
    if isinstance(value, dict):
        if model_id is not None and isinstance(value.get(model_id), dict):
            return value[model_id]
        if "ok" in value:
            return value
    return None


def classify(model, probe_result=None):
    """Assign one role, or None when evidence is insufficient (-> candidates).

    Evidence rules (NVIDIA's catalog carries no capability fields):
      * specialist/sensitive names -> None (candidate). The negative-token
        pass runs first, so no family token or probe can promote them.
      * embed  -- explicit id tokens (embed/retriever/nvclip) are sufficient.
      * decide -- explicit id tokens PLUS a successful probe. A name alone is
                  never promoted into this high-stakes role.
      * chat   -- a known generative model family in the id.
      * anything uncertain -> None.
    """
    if not isinstance(model, dict):
        return None
    ident = str(model.get("id") or "").lower()
    if not ident:
        return None

    # Negative pass before every role hint: a specialist id is a candidate,
    # never a chat/embed/decide promotion, even with a successful probe.
    if any(token in ident for token in NEGATIVE_ID_TOKENS):
        return None

    if probe_result is None:
        for key in ("_probe", "probe"):
            if key in model:
                probe_result = model[key]
                break
    if probe_result is None:
        for key in ("_probe_ok", "probe_ok"):
            if key in model:
                probe_result = bool(model[key])
                break
    entry = _as_probe_result(probe_result, ident)
    probe_ok = bool(entry and entry.get("ok") is True)

    if any(token in ident for token in EMBED_NAME_TOKENS):
        return "embed"
    if any(token in ident for token in DECIDE_NAME_TOKENS):
        return "decide" if probe_ok else None
    if any(token in ident for token in CHAT_FAMILY_TOKENS):
        return "chat"
    return None


def _probe_failed(probe, model_id):
    if not isinstance(probe, dict):
        return False
    entry = probe.get(model_id)
    return isinstance(entry, dict) and entry.get("ok") is False


def build_plan(current, catalog, probe=None):
    """Diff active roles against a fresh catalog; return {"manifest", "report"}.

    An id is eligible only because it is present in the live catalog -- there is
    no pricing signal to apply. Delisted and probe-failed ids move to ``retired``
    with a reason; returning retired ids are re-activated in place. Retired
    history is never hard-deleted or rewritten.
    """
    plan = _normalize_manifest(copy.deepcopy(current))
    by_id = {
        model["id"]: model
        for model in (catalog or [])
        if isinstance(model, dict) and model.get("id")
    }
    probe_map = probe if isinstance(probe, dict) else {}
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
            elif _probe_failed(probe, model_id):
                reason = "probe_failed"
            if reason is not None:
                if model_id not in retired_ids:
                    plan["retired"].append(
                        {"id": model_id, "role": role, "reason": reason,
                         "since": now, "reactivated_at": None}
                    )
                    retired_ids.add(model_id)
                    retired_now.append(model_id)
                plan["models"].pop(model_id, None)
                continue
            survivors.append(model_id)
            active_ids.add(model_id)
            plan["models"][model_id] = _model_meta(model, role)
        plan["roles"][role] = survivors

    # Re-activation: a retired id that is alive again returns to its classified
    # role. The history entry stays and is stamped; it is never also an "added".
    for entry in plan["retired"]:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not model_id:
            continue
        model = by_id.get(model_id)
        if model is None or model_id in active_ids:
            continue
        if _probe_failed(probe, model_id):
            continue
        role = classify(model, probe_result=probe_map.get(model_id))
        recorded = entry.get("role")
        if role is None and recorded == "chat":
            # A previously classified chat model returning to the catalog keeps
            # its recorded role: that classification is prior evidence, and chat
            # is the low-stakes role. decide/embed still require fresh evidence.
            role = "chat"
        if role is None:  # uncertain -> candidates, never promoted by guesswork
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
        role = classify(model, probe_result=probe_map.get(model_id))
        if role is None:
            if model_id not in candidates and model_id not in retired_ids and model_id not in active_ids:
                candidates.append(model_id)
            continue
        if model_id in retired_ids or model_id in active_ids:
            continue
        if _probe_failed(probe, model_id):
            plan["retired"].append(
                {"id": model_id, "role": role, "reason": "probe_failed",
                 "since": now, "reactivated_at": None}
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
    plan["schema_version"] = SCHEMA_VERSION

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


def _probe_one(model_id, role, api_key, base_url, timeout):
    if role == "embed":
        url = f"{base_url}/embeddings"
        payload = {"model": model_id, "input": ["ping"]}
    else:  # chat and decide both use the chat-completions endpoint
        url = f"{base_url}/chat/completions"
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
    """Opt-in live reachability check; never called implicitly by build_plan.

    Without NVIDIA_API_KEY no request is made -- every active id is reported as
    a failed probe so the caller can never mistake an unauthenticated run for a
    healthy one.
    """
    results = {}
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    active = []
    roles = manifest.get("roles", {}) if isinstance(manifest, dict) else {}
    for role in ROLES:
        active.extend((role, model_id) for model_id in roles.get(role, []))
    if not api_key:
        for _, model_id in active:
            results[model_id] = {"ok": False, "error": f"{API_KEY_ENV} not configured"}
        return results
    base_url = os.environ.get("NVIDIA_BASE_URL", DEFAULT_BASE_URL).strip().rstrip("/")
    for role, model_id in active:
        results[model_id] = _probe_one(model_id, role, api_key, base_url, timeout)
    return results


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="nim_catalog.py",
        description="Reconcile the nvidia-nim catalog manifest against the public NVIDIA model catalog.",
        epilog="Exit codes: 0 success; 1 runtime error or drift; 2 usage error.",
    )
    parser.add_argument("--check", action="store_true", help="read-only drift check")
    parser.add_argument("--apply", action="store_true", help="write the reconciled manifest")
    parser.add_argument(
        "--probe", action="store_true",
        help="opt-in live endpoint probe (requires NVIDIA_API_KEY; spends quota)",
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
    if args.probe and not os.environ.get(API_KEY_ENV, "").strip():
        sys.stderr.write(f"usage: --probe requires {API_KEY_ENV}\n")
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
                "[nim_catalog] %s: drift=%s added=%s retired=%s reactivated=%d "
                "candidates=%d\n"
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
        sys.stderr.write(f"[nim_catalog] {exc}\n")
        return 1


if __name__ == "__main__":
    sys.exit(main())
