#!/usr/bin/env python3
"""
nim_client.py — NVIDIA NIM / API Catalog Multi-Agent & Multimodal Gateway
Implements the Uber OmniMCP & Kem Glitch Autonomous Subagent Protocol:
  - Autonomous Subagent Loop (`agent`) with compound bash batching (`run_bash_batch`)
  - Streaming Chat & Reasoning Extraction (`chat`) with `--thinking` trace
  - Calibrated Decision Routing (`decide`) with structured option scoring
  - Batched Vector Embeddings (`embed`) using NVIDIA NeMo Retriever / Embed
  - Multi-Key Pool & Automatic Rotation on 429/403
  - Response Projection & Disk Buffering (--out, --project, --out-json)
  - Zero External Dependencies (Python standard library urllib.request)
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, Generator, List, Optional, Tuple, Union

# Catalog reconciliation ships as a parallel slice. Import defensively so this
# client keeps working with embedded bootstrap ids until that module is present.
try:
    import nim_catalog
except Exception as exc:  # pragma: no cover - only when the parallel slice is absent
    nim_catalog = None
    sys.stderr.write(f"[nvidia-nim] nim_catalog unavailable ({exc}); using embedded bootstrap ids.\n")

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_CHAT_MODEL = "z-ai/glm-5.3-flash"
DEFAULT_EMBED_MODEL = "nvidia/llama-nemotron-embed-vl-1b-v2"

POPULAR_MODELS = [
    {"id": "deepseek-ai/deepseek-v4.1-flash", "name": "DeepSeek V4.1 Flash (Frontier Speed)", "type": "chat/reasoning"},
    {"id": "z-ai/glm-5.3-flash", "name": "GLM 5.3 Flash (Fast Reasoning)", "type": "chat/reasoning"},
    {"id": "z-ai/glm-5.3", "name": "GLM 5.3 (Heavy Reasoning)", "type": "chat/reasoning"},
    {"id": "deepseek-ai/deepseek-r1", "name": "DeepSeek R1 (Reasoning)", "type": "reasoning"},
    {"id": "deepseek-ai/deepseek-v3", "name": "DeepSeek V3", "type": "chat"},
    {"id": "meta/llama-3.3-70b-instruct", "name": "Llama 3.3 70B Instruct", "type": "chat"},
    {"id": "nvidia/llama-3.1-nemotron-70b-instruct", "name": "Nemotron 70B Instruct", "type": "chat"},
    {"id": "qwen/qwen2.5-coder-32b-instruct", "name": "Qwen 2.5 Coder 32B", "type": "code"},
    {"id": "nvidia/llama-nemotron-embed-vl-1b-v2", "name": "Nemotron Embed VL 1B", "type": "embed"},
    {"id": "snowflake/arctic-embed-l", "name": "Snowflake Arctic Embed L", "type": "embed"},
]

BOOTSTRAP_CHAT_IDS = [DEFAULT_CHAT_MODEL] + [
    m["id"] for m in POPULAR_MODELS
    if m["type"] in ("chat", "code", "reasoning", "chat/reasoning") and m["id"] != DEFAULT_CHAT_MODEL
]
BOOTSTRAP_EMBED_IDS = [m["id"] for m in POPULAR_MODELS if m["type"] == "embed"]
# Decide ids are only trusted when a probe promoted them; never name-guessed.
BOOTSTRAP_DECIDE_IDS: List[str] = []

CATALOG_ENV_VAR = "NIM_CATALOG_PATH"
DEFAULT_CATALOG_PATH = Path(__file__).resolve().parent.parent / "catalog.json"
CATALOG_ROLES = ("chat", "embed", "decide")

SUBAGENT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_bash_batch",
            "description": (
                "Execute an ordered sequence of shell commands inside a single compound bash environment. "
                "Commands share directory context (e.g. `cd dir` affects subsequent commands). "
                "CRITICAL: Always batch reconnaissance, file inspection, edits, and test runs together "
                "in the `commands` array to minimize API turn consumption."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "commands": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Ordered list of shell commands to execute sequentially.",
                    }
                },
                "required": ["commands"],
            },
        },
    }
]


def resolve_api_keys() -> List[str]:
    """Resolves all available NVIDIA_API_KEYS into a list for rotation/failover."""
    keys = []

    # Check env var directly
    env_keys = os.environ.get("NVIDIA_API_KEYS")
    if env_keys:
        for k in env_keys.split(","):
            k = k.strip()
            if k and k.startswith("nvapi-") and k not in keys:
                keys.append(k)

    env_single = os.environ.get("NVIDIA_API_KEY")
    if env_single and env_single.strip().startswith("nvapi-") and env_single.strip() not in keys:
        keys.append(env_single.strip())

    search_paths = [
        Path.home() / ".agent_keys.env",
        Path.cwd() / ".env",
        Path(__file__).resolve().parent.parent / ".env",
        Path.home() / ".env",
        Path.home() / ".config" / "nvidia" / "nim.env",
    ]

    for p in search_paths:
        if not p.is_file():
            continue
        try:
            for line in p.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                m_multi = re.match(r'^(?:export\s+)?NVIDIA_API_KEYS\s*=\s*["\']?([^"\']+)["\']?', line)
                if m_multi:
                    for k in m_multi.group(1).split(","):
                        k = k.strip()
                        if k and k.startswith("nvapi-") and k not in keys:
                            keys.append(k)
                m_single = re.match(r'^(?:export\s+)?NVIDIA_API_KEY\s*=\s*["\']?([^"\']+)["\']?', line)
                if m_single:
                    k = m_single.group(1).strip()
                    if k and k.startswith("nvapi-") and k not in keys:
                        keys.append(k)
        except Exception:
            continue

    return keys


def resolve_api_key() -> Optional[str]:
    keys = resolve_api_keys()
    return keys[0] if keys else None


def resolve_base_url() -> str:
    env_val = os.environ.get("NVIDIA_BASE_URL")
    if env_val and env_val.strip():
        return env_val.strip().rstrip("/")
    return DEFAULT_BASE_URL


def resolve_catalog_path() -> Path:
    env_val = os.environ.get(CATALOG_ENV_VAR)
    if env_val and env_val.strip():
        return Path(env_val.strip()).expanduser()
    return DEFAULT_CATALOG_PATH


def load_catalog_manifest() -> Optional[Dict[str, Any]]:
    """Return the manifest when nim_catalog is usable; None means use bootstrap ids."""
    if nim_catalog is None:
        return None
    try:
        manifest = nim_catalog.load_manifest(str(resolve_catalog_path()))
        return manifest if isinstance(manifest, dict) else None
    except Exception as exc:
        sys.stderr.write(f"[nvidia-nim] catalog manifest unavailable ({exc}); using bootstrap ids.\n")
        return None


def _active_ids(role: str, bootstrap: List[str]) -> List[str]:
    manifest = load_catalog_manifest()
    if manifest is None:
        return list(bootstrap)
    roles = manifest.get("roles")
    ids = roles.get(role) if isinstance(roles, dict) else None
    if not isinstance(ids, list):
        return list(bootstrap)
    return [str(i) for i in ids if i]


def load_active_chat_ids() -> List[str]:
    return _active_ids("chat", BOOTSTRAP_CHAT_IDS)


def load_active_embed_ids() -> List[str]:
    return _active_ids("embed", BOOTSTRAP_EMBED_IDS)


def load_active_decide_ids() -> List[str]:
    return _active_ids("decide", BOOTSTRAP_DECIDE_IDS)


def resolve_chat_model(model: Optional[str] = None) -> str:
    if model:
        return model
    ids = load_active_chat_ids() or BOOTSTRAP_CHAT_IDS
    return ids[0] if ids else DEFAULT_CHAT_MODEL


def resolve_embed_model(model: Optional[str] = None) -> str:
    if model:
        return model
    ids = load_active_embed_ids() or BOOTSTRAP_EMBED_IDS
    return ids[0] if ids else DEFAULT_EMBED_MODEL


def resolve_decide_model(model: Optional[str] = None) -> str:
    if model:
        return model
    decide_ids = load_active_decide_ids()
    if decide_ids:
        return decide_ids[0]
    return resolve_chat_model()


class KeyRotator:
    def __init__(self, keys: Optional[List[str]] = None):
        self.keys = keys or resolve_api_keys()
        self.index = 0

    def get_current_key(self) -> str:
        if not self.keys:
            raise ValueError(
                "No NVIDIA_API_KEY configured.\n"
                "Set it via environment variable: export NVIDIA_API_KEY='nvapi-...'\n"
                "or add to ~/.agent_keys.env or /run/media/rodri/AI/skills/nvidia-nim/.env"
            )
        return self.keys[self.index % len(self.keys)]

    def rotate(self) -> str:
        if len(self.keys) > 1:
            self.index = (self.index + 1) % len(self.keys)
            sys.stderr.write(f"[nvidia-nim] Rotating to key index {self.index + 1}/{len(self.keys)}...\n")
        return self.get_current_key()


class NimClient:
    """Zero-dependency HTTP client for NVIDIA NIM / API Catalog with key rotation."""

    def __init__(self, api_key: Optional[str] = None, base_url: Optional[str] = None):
        keys = [api_key] if api_key else resolve_api_keys()
        self.rotator = KeyRotator(keys)
        self.base_url = (base_url or resolve_base_url()).rstrip("/")

    @property
    def api_key(self) -> str:
        return self.rotator.get_current_key()

    def is_configured(self) -> bool:
        return bool(self.rotator.keys and any(k.startswith("nvapi-") for k in self.rotator.keys))

    def _post_json(self, endpoint: str, payload: dict, timeout: int = 360, max_retries: int = 3) -> urllib.request.urlopen:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        last_err = None

        for attempt in range(max_retries):
            key = self.rotator.get_current_key()
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                    "User-Agent": "NIM-Subagent-Client/2.0",
                },
                method="POST",
            )
            try:
                return urllib.request.urlopen(req, timeout=timeout)
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="replace")
                last_err = f"HTTP {e.code}: {err_body}"
                sys.stderr.write(f"[nvidia-nim] {endpoint} error {e.code} (attempt {attempt + 1}/{max_retries})\n")
                if e.code in (429, 403, 503):
                    self.rotator.rotate()
                    time.sleep(1.5)
                    continue
                raise RuntimeError(f"NVIDIA NIM API Error ({e.code}): {err_body}") from e
            except urllib.error.URLError as e:
                last_err = f"URLError: {e.reason}"
                self.rotator.rotate()
                time.sleep(1.0)
                continue

        raise RuntimeError(f"All retries exhausted for {url}. Last error: {last_err}")

    def chat_completion(
        self,
        messages: List[Dict[str, Any]],
        model: Optional[str] = None,
        temperature: float = 0.5,
        top_p: float = 1.0,
        max_tokens: int = 1024,
        stream: bool = False,
        tools: Optional[List[Dict[str, Any]]] = None,
        include_reasoning: bool = False,
        timeout: int = 360,
    ) -> Union[Dict, Generator[Dict[str, Any], None, None]]:
        model = resolve_chat_model(model)
        payload = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "top_p": top_p,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            payload["tools"] = tools

        resp = self._post_json("chat/completions", payload, timeout=timeout)
        generator = self._stream_generator(resp)

        if stream:
            return generator

        reasoning_parts = []
        content_parts = []
        tool_calls_acc: Dict[int, Dict[str, Any]] = {}
        model_name = model

        for item in generator:
            if "model" in item:
                model_name = item["model"]
            if item.get("reasoning"):
                reasoning_parts.append(item["reasoning"])
            if item.get("content"):
                content_parts.append(item["content"])
            if item.get("tool_calls"):
                for tc in item["tool_calls"]:
                    idx = tc.get("index", 0)
                    if idx not in tool_calls_acc:
                        tool_calls_acc[idx] = {
                            "id": tc.get("id", f"call_{idx}"),
                            "type": "function",
                            "function": {"name": "", "arguments": ""},
                        }
                    fn = tc.get("function", {})
                    if fn.get("name"):
                        tool_calls_acc[idx]["function"]["name"] = fn["name"]
                    if fn.get("arguments"):
                        tool_calls_acc[idx]["function"]["arguments"] += fn["arguments"]

        full_content = "".join(content_parts)
        full_reasoning = "".join(reasoning_parts)

        if not full_content.strip() and full_reasoning.strip() and not tool_calls_acc:
            full_content = full_reasoning

        message_obj: Dict[str, Any] = {
            "role": "assistant",
            "content": full_content if full_content else None,
        }
        if include_reasoning and full_reasoning:
            message_obj["reasoning_content"] = full_reasoning

        if tool_calls_acc:
            message_obj["tool_calls"] = [tool_calls_acc[k] for k in sorted(tool_calls_acc.keys())]

        return {
            "id": f"nim-{model_name}",
            "object": "chat.completion",
            "model": model_name,
            "choices": [
                {
                    "index": 0,
                    "message": message_obj,
                    "finish_reason": "tool_calls" if tool_calls_acc else "stop",
                }
            ],
        }

    def _stream_generator(self, resp) -> Generator[Dict[str, Any], None, None]:
        raw_lines = []
        is_sse = False
        for line in resp:
            line_str = line.decode("utf-8", errors="replace").strip()
            if not line_str or line_str.startswith(":"):
                continue
            if line_str.startswith("data: "):
                is_sse = True
                data_part = line_str[6:].strip()
                if data_part == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_part)
                    model_id = chunk.get("model", "")
                    choices = chunk.get("choices", [{}])
                    delta = choices[0].get("delta", {}) if choices else {}
                    content = delta.get("content") or ""
                    reasoning = delta.get("reasoning_content") or ""
                    tool_calls = delta.get("tool_calls") or []

                    if content or reasoning or tool_calls:
                        yield {
                            "content": content,
                            "reasoning": reasoning,
                            "tool_calls": tool_calls,
                            "model": model_id,
                        }
                except Exception:
                    continue
            else:
                raw_lines.append(line_str)

        if not is_sse and raw_lines:
            try:
                full_json = json.loads("\n".join(raw_lines))
                choices = full_json.get("choices", [{}])
                msg = choices[0].get("message", {}) if choices else {}
                content = msg.get("content") or ""
                reasoning = msg.get("reasoning_content") or ""
                tool_calls = msg.get("tool_calls") or []
                model_id = full_json.get("model", "")
                if content or reasoning or tool_calls:
                    yield {
                        "content": content,
                        "reasoning": reasoning,
                        "tool_calls": tool_calls,
                        "model": model_id,
                    }
            except Exception:
                pass

    def embeddings(
        self,
        inputs: List[str],
        model: Optional[str] = None,
        input_type: str = "passage",
    ) -> List[Dict[str, Any]]:
        """Generates vector embeddings for a list of strings."""
        model = resolve_embed_model(model)
        payload: Dict[str, Any] = {
            "model": model,
            "input": inputs,
        }
        if "nemotron" in model or "nvidia" in model:
            payload["input_type"] = input_type

        resp = self._post_json("embeddings", payload, timeout=60)
        data = json.loads(resp.read().decode("utf-8"))
        return data.get("data", [])


# --- COMPOUND BASH EXECUTION ---

def execute_compound_batch(commands: List[str], cwd: Optional[str] = None, timeout_total: int = 180) -> str:
    """Executes multiple shell commands in a single subshell preserving state across lines."""
    if isinstance(commands, str):
        commands = [commands]

    script_lines = [
        "#!/usr/bin/env bash",
        "set -eo pipefail",
    ]
    for idx, cmd in enumerate(commands):
        escaped_cmd = cmd.replace("'", "'\\''")
        script_lines.append(f"echo '--- [STEP {idx + 1}/{len(commands)}] $ {escaped_cmd} ---'")
        script_lines.append(cmd)

    full_script = "\n".join(script_lines)

    try:
        proc = subprocess.run(
            ["bash", "-c", full_script],
            cwd=cwd or os.getcwd(),
            capture_output=True,
            text=True,
            timeout=timeout_total,
        )
        combined = (proc.stdout + "\n" + proc.stderr).strip()
        exit_msg = f"\n[Batch Finished with exit code {proc.returncode}]"
        return (combined + exit_msg)[:12000]
    except subprocess.TimeoutExpired as te:
        stdout = te.stdout.decode("utf-8", errors="ignore") if isinstance(te.stdout, bytes) else (te.stdout or "")
        return f"{stdout}\n[ERROR: Batch timed out after {timeout_total}s]"
    except Exception as ex:
        return f"[ERROR: Execution failure: {ex}]"


# --- HIGH LEVEL WORKFLOWS ---

def run_agent_loop(
    prompt: str,
    model: Optional[str] = None,
    max_turns: int = 10,
    out_file: Optional[str] = None,
    cwd: Optional[str] = None,
) -> str:
    """Runs an autonomous coding and verification subagent loop with compound bash batching."""
    model = resolve_chat_model(model)
    client = NimClient()
    system_prompt = (
        "You are an autonomous engineering subagent powered by NVIDIA NIM.\n"
        "You have direct bash execution via `run_bash_batch`.\n"
        "CRITICAL: Always batch multiple shell commands (inspect, edit, test, summarize) together into "
        "the `commands` array in a single turn to minimize token consumption and round-trips.\n"
        "Perform the requested task, verify the result with tests or checks, and produce a concise final report.\n\n"
        "Available Workstation & Browser Verification CLIs in PATH:\n"
        "- `fast-cdp verify <url> [--assert-selector <sel>] [--assert-text <txt>] [--screenshot <path>] [--json]`: Sub-second native Chrome DevTools Protocol verification on port :9222.\n"
        "- `fast-cdp snap <url>`: Instant viewport accessibility text snapshot.\n"
        "- `ocr read <file>`: LightOnOCR-3-0.8B document and image OCR.\n"
        "- `jev bool / choice / score`: Calibrated non-generative decisions.\n"
        "- `audiocpp tts / asr`: Speech synthesis and verbatim transcription.\n"
        "- `local-llm \"<prompt>\"`: Local Qwen3.6-35B coder on :8080 (see the `local-llm` skill).\n"
    )
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    final_content = ""

    for turn in range(1, max_turns + 1):
        sys.stderr.write(f"\n[NIM Subagent | Turn {turn}/{max_turns}] Invoking {model}...\n")
        res = client.chat_completion(
            messages=messages,
            model=model,
            tools=SUBAGENT_TOOLS,
            include_reasoning=True,
        )
        msg = res["choices"][0]["message"]
        messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            final_content = msg.get("content", "") or ""
            print(f"\n--- NIM Subagent Completed via {model} in {turn} turn(s) ---")
            print(final_content)
            if out_file:
                out_p = Path(out_file).resolve()
                out_p.parent.mkdir(parents=True, exist_ok=True)
                out_p.write_text(final_content, encoding="utf-8")
                print(f"[NIM Subagent] Report saved to: {out_p}")
            return final_content

        for tc in tool_calls:
            fn_name = tc.get("function", {}).get("name")
            raw_args = tc.get("function", {}).get("arguments", "{}")
            try:
                args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args
            except Exception:
                args = {}

            if fn_name == "run_bash_batch":
                cmds = args.get("commands", [])
                sys.stderr.write(f"  [Turn {turn}] Executing batch of {len(cmds)} command(s)...\n")
                output = execute_compound_batch(cmds, cwd=cwd)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": output,
                    }
                )

    sys.stderr.write(f"\n[nvidia-nim] Subagent reached maximum turns ({max_turns}).\n")
    return final_content or (messages[-1].get("content") or "")


def run_decide(query: str, options: Optional[List[str]] = None, model: Optional[str] = None) -> Dict[str, Any]:
    """Calibrated decision routing and option selection."""
    model = resolve_decide_model(model)
    client = NimClient()
    prompt_text = query
    if options:
        opts_formatted = "\n".join(f"- {o}" for o in options)
        prompt_text = f"{query}\n\nSelect strictly one of the following options:\n{opts_formatted}\n\nRespond with a JSON object: {{\"choice\": \"<selected_option>\", \"confidence\": <float 0.0-1.0>, \"rationale\": \"<one-sentence rationale>\"}}"

    res = client.chat_completion(
        messages=[
            {"role": "system", "content": "You are a calibrated zero-shot decision router. Output valid JSON."},
            {"role": "user", "content": prompt_text},
        ],
        model=model,
        temperature=0.1,
    )
    raw = res["choices"][0]["message"]["content"]
    try:
        # Extract json chunk if wrapped in markdown
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            parsed = json.loads(m.group(0))
            return {"model": model, **parsed}
    except Exception:
        pass
    return {"model": model, "choice": raw.strip()}


def run_batched_embeddings(
    inputs: List[str],
    model: Optional[str] = None,
    out_json: Optional[str] = None,
) -> Dict[str, Any]:
    """Embeds an array of texts or file contents."""
    model = resolve_embed_model(model)
    client = NimClient()
    resolved_texts = []
    for item in inputs:
        p = Path(item)
        if p.is_file():
            resolved_texts.append(p.read_text(errors="ignore")[:6000])
        else:
            resolved_texts.append(item)

    data = client.embeddings(resolved_texts, model=model)
    vectors = [
        {
            "index": idx,
            "source": inputs[idx],
            "dimensions": len(row.get("embedding", [])),
            "embedding": row.get("embedding", []),
        }
        for idx, row in enumerate(data)
    ]
    result = {"model": model, "count": len(vectors), "results": vectors}
    if out_json:
        out_p = Path(out_json).resolve()
        out_p.parent.mkdir(parents=True, exist_ok=True)
        out_p.write_text(json.dumps(result, indent=2), encoding="utf-8")

    return {
        "model": model,
        "count": len(vectors),
        "dimensions": vectors[0]["dimensions"] if vectors else 0,
        "saved_to": out_json,
        "preview_dims": vectors[0]["embedding"][:5] if vectors else [],
    }


def chat(
    prompt: str,
    system: str = "You are a helpful assistant.",
    model: Optional[str] = None,
    temperature: float = 0.5,
    top_p: float = 1.0,
    max_tokens: int = 1024,
    api_key: Optional[str] = None,
) -> str:
    """Convenience helper for one-shot chat queries."""
    model = resolve_chat_model(model)
    client = NimClient(api_key=api_key)
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": prompt},
    ]
    res = client.chat_completion(
        messages=messages,
        model=model,
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
        stream=False,
    )
    return res["choices"][0]["message"]["content"]


def _catalog_id_set(catalog: Any) -> set:
    if isinstance(catalog, dict) and "data" not in catalog and "models" not in catalog:
        return {str(k) for k in catalog}
    data = (catalog.get("data") or catalog.get("models") or []) if isinstance(catalog, dict) else (catalog or [])
    ids = set()
    for item in data:
        if isinstance(item, str):
            ids.add(item)
        elif isinstance(item, dict) and item.get("id"):
            ids.add(str(item["id"]))
    return ids


def catalog_summary() -> Dict[str, Any]:
    """Compact doctor status; drift is null unless a real catalog diff was possible."""
    manifest = load_catalog_manifest()
    roles = manifest.get("roles") if manifest else None
    roles = roles if isinstance(roles, dict) else {}
    retired = manifest.get("retired") if manifest else None
    summary: Dict[str, Any] = {
        "drift": None,
        "retired_count": len(retired) if isinstance(retired, list) else 0,
        "degraded_roles": [r for r in CATALOG_ROLES if not (roles.get(r) or [])],
    }
    if manifest is None:
        summary["note"] = "manifest unavailable"
        return summary
    if nim_catalog is None:
        summary["note"] = "nim_catalog unavailable"
        return summary
    try:
        live_ids = _catalog_id_set(nim_catalog.fetch_catalog())
    except Exception as exc:
        summary["note"] = f"live catalog unreachable ({type(exc).__name__})"
        return summary
    # Drift counts live ids the manifest does not account for. Candidates are
    # unclassified but intentional live ids, and retired entries are history;
    # neither is drift. Comparing against active role ids alone reported the
    # whole candidate pool as permanent drift.
    accounted_ids = {
        str(i) for role in CATALOG_ROLES for i in (roles.get(role) or []) if i
    }
    for key in ("candidates", "retired"):
        entries = manifest.get(key)
        if not isinstance(entries, list):
            continue
        for entry in entries:
            mid = entry.get("id") if isinstance(entry, dict) else entry
            if mid:
                accounted_ids.add(str(mid))
    summary["drift"] = len(live_ids - accounted_ids)
    return summary


def run_doctor():
    keys = resolve_api_keys()
    base_url = resolve_base_url()
    print("🔍 [nvidia-nim] Diagnostic Health Check")
    print(f"  Base URL    : {base_url}")
    print(f"  Key Pool    : {len(keys)} key(s) detected")
    for idx, k in enumerate(keys, 1):
        masked = f"{k[:7]}...{k[-4:]}" if len(k) > 12 else "***"
        print(f"    [{idx}] {masked}")

    if keys:
        print("  Status      : ✅ Ready for multi-turn inference, subagents, and embeddings")
    else:
        print("  Status      : ⚠️ Requires NVIDIA_API_KEY in environment or .env")
        print("\nGet your API key at: https://build.nvidia.com")
        print("Save to ~/.agent_keys.env or /run/media/rodri/AI/skills/nvidia-nim/.env")
    print(f"  Catalog    : {json.dumps(catalog_summary())}")


def run_models():
    manifest = load_catalog_manifest()
    if manifest is not None:
        models = manifest.get("models")
        rows = [
            (str(mid), str((info or {}).get("name") or mid), str((info or {}).get("role") or ""))
            for mid, info in sorted((models or {}).items())
        ]
    else:
        rows = [(m["id"], m["name"], m["type"]) for m in POPULAR_MODELS]
    print(f"{'MODEL ID':<44} {'NAME':<32} {'TYPE':<16}")
    print("-" * 96)
    for mid, name, model_type in rows:
        print(f"{mid:<44} {name:<32} {model_type:<16}")


def _delegate_catalog(argv: List[str]) -> int:
    if nim_catalog is None:
        sys.stderr.write("[nvidia-nim] nim_catalog is unavailable; cannot run 'catalog'.\n")
        return 2
    result = nim_catalog.main(argv)
    return int(result) if isinstance(result, int) else 0


def main():
    argv = list(sys.argv[1:])
    if argv and argv[0] == "catalog":
        return _delegate_catalog(argv[1:])

    parser = argparse.ArgumentParser(epilog='Exit codes: 0 success; 1 runtime/validation error; 2 invalid arguments (usage error); other non-zero values are script-specific.', description="NVIDIA NIM Multi-Agent & Multimodal Gateway (Uber Protocol)")
    subparsers = parser.add_subparsers(dest="command", help="Available subcommands")

    # 1. agent subcommand
    agent_p = subparsers.add_parser("agent", help="Run autonomous subagent loop with compound bash batching")
    agent_p.add_argument("prompt", nargs="?", default=None, help="Task description")
    agent_p.add_argument("--prompt", "-p", dest="prompt_flag", help="Task description")
    agent_p.add_argument("--model", "-m", default=None, help="Model slug (default: active catalog chat id)")
    agent_p.add_argument("--max-turns", type=int, metavar="LIMIT", default=10, help="Maximum agent turns")
    agent_p.add_argument("--out", "-o", help="Save final subagent report to file")
    agent_p.add_argument("--cwd", help="Working directory for subagent execution")

    # 2. chat subcommand
    chat_p = subparsers.add_parser("chat", help="Send chat completion prompt")
    chat_p.add_argument("prompt", nargs="?", default=None, help="User prompt (or read from stdin)")
    chat_p.add_argument("--model", "-m", default=None, help="Model slug (default: active catalog chat id)")
    chat_p.add_argument("--system", "-s", default="You are a helpful assistant.", help="System prompt")
    chat_p.add_argument("--temperature", "-t", type=float, default=0.5, help="Sampling temperature")
    chat_p.add_argument("--top-p", type=float, metavar="SCORE", default=1.0, help="Top-p sampling")
    chat_p.add_argument("--max-tokens", type=int, metavar="N", default=1024, help="Max completion tokens")
    chat_p.add_argument("--stream", action="store_true", help="Stream tokens live to stdout")
    chat_p.add_argument("--thinking", action="store_true", help="Display reasoning tokens / chain-of-thought")
    chat_p.add_argument("--out", "-o", help="Buffer output to disk file (Kem Glitch context reduction)")
    chat_p.add_argument("--project", action="store_true", help="Project summary (lines/words/preview)")
    chat_p.add_argument("--json", action="store_true", help="Output raw JSON response")

    # 3. decide subcommand
    decide_p = subparsers.add_parser("decide", help="Calibrated decision routing")
    decide_p.add_argument("query", nargs="?", default=None, help="Routing prompt or question")
    decide_p.add_argument("--options", nargs="*", default=None, help="List of candidate options")
    decide_p.add_argument("--model", "-m", default=None, help="Model override (default: probed decide id or active chat id)")

    # 4. embed subcommand
    embed_p = subparsers.add_parser("embed", help="Batched text & file embeddings")
    embed_p.add_argument("inputs", nargs="*", default=None, help="Texts or file paths to embed")
    embed_p.add_argument("--model", "-m", default=None, help="Embedding model (default: active catalog embed id)")
    embed_p.add_argument("--out-json", help="Save vector embeddings to JSON file")

    # 5. models subcommand
    subparsers.add_parser("models", help="List active models from the catalog manifest")

    # 6. doctor subcommand
    subparsers.add_parser("doctor", help="Check API key and endpoint configuration")

    # 7. catalog subcommand (args forwarded before argparse by _delegate_catalog)
    subparsers.add_parser("catalog", help="Reconcile the NIM catalog (forwarded to nim_catalog)")

    args = parser.parse_args()

    if args.command == "doctor":
        run_doctor()
        sys.exit(0)

    if args.command == "models":
        run_models()
        sys.exit(0)

    if args.command == "agent":
        prompt = args.prompt_flag or args.prompt
        if not prompt and not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()
        if not prompt:
            print("Error: Prompt is required for agent mode.", file=sys.stderr)
            sys.exit(1)
        run_agent_loop(prompt, model=args.model, max_turns=args.max_turns, out_file=args.out, cwd=args.cwd)
        return

    if args.command == "decide":
        query = args.query
        if not query and not sys.stdin.isatty():
            query = sys.stdin.read().strip()
        if not query:
            print("Error: Query is required for decide mode.", file=sys.stderr)
            sys.exit(1)
        res = run_decide(query, options=args.options, model=args.model)
        print(json.dumps(res, indent=2))
        return

    if args.command == "embed":
        inputs = args.inputs
        if not inputs:
            print("Error: At least one text or file input required for embed mode.", file=sys.stderr)
            sys.exit(1)
        res = run_batched_embeddings(inputs, model=args.model, out_json=args.out_json)
        print(json.dumps(res, indent=2))
        return

    if args.command == "chat" or (args.command is None and len(sys.argv) > 1 and not sys.argv[1].startswith("-")):
        prompt = getattr(args, "prompt", None)
        if not prompt and not sys.stdin.isatty():
            prompt = sys.stdin.read().strip()

        if not prompt:
            print("Error: Prompt is required. Pass as argument or pipe via stdin.", file=sys.stderr)
            sys.exit(1)

        model = resolve_chat_model(args.model)
        client = NimClient()
        messages = [
            {"role": "system", "content": args.system},
            {"role": "user", "content": prompt},
        ]

        try:
            if args.stream and not args.out and not args.project and not args.json:
                gen = client.chat_completion(
                    messages=messages,
                    model=model,
                    temperature=args.temperature,
                    top_p=args.top_p,
                    max_tokens=args.max_tokens,
                    stream=True,
                )
                in_thinking = False
                for chunk in gen:
                    reasoning = chunk.get("reasoning", "")
                    content = chunk.get("content", "")

                    if reasoning and args.thinking:
                        if not in_thinking:
                            sys.stdout.write("\033[90m[Thinking: ")
                            in_thinking = True
                        sys.stdout.write(reasoning)
                        sys.stdout.flush()

                    if content:
                        if in_thinking:
                            sys.stdout.write("]\033[0m\n\n")
                            in_thinking = False
                        sys.stdout.write(content)
                        sys.stdout.flush()

                if in_thinking:
                    sys.stdout.write("]\033[0m\n")
                sys.stdout.write("\n")
                return

            res = client.chat_completion(
                messages=messages,
                model=model,
                temperature=args.temperature,
                top_p=args.top_p,
                max_tokens=args.max_tokens,
                stream=False,
                include_reasoning=args.thinking,
            )

            if args.json:
                print(json.dumps(res, indent=2))
                return

            text = res["choices"][0]["message"]["content"]
            reasoning = res["choices"][0]["message"].get("reasoning_content")

            if args.thinking and reasoning:
                print(f"\033[90m[Thinking:\n{reasoning}\n]\033[0m\n")

            if args.out:
                out_path = Path(args.out).resolve()
                out_path.parent.mkdir(parents=True, exist_ok=True)
                out_path.write_text(text, encoding="utf-8")
                lines = len(text.splitlines())
                words = len(text.split())
                print(f"[nvidia-nim] Written {len(text)} bytes ({lines} lines, {words} words) -> {out_path}")
                if args.project:
                    preview = "\n".join(text.splitlines()[:3])
                    print(f"--- Preview ---\n{preview}\n...")
                return

            if args.project:
                lines = len(text.splitlines())
                words = len(text.split())
                preview = "\n".join(text.splitlines()[:4])
                print(f"[nvidia-nim] {lines} lines, {words} words, model={model}")
                print(f"--- Preview ---\n{preview}\n...")
                return

            print(text)

        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    parser.print_help()


if __name__ == "__main__":
    sys.exit(main())
