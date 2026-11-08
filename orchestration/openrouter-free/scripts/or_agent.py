#!/usr/bin/env python3
import argparse
import base64
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def _load_env_fallbacks():
    candidates = [
        Path.home() / ".agent_keys.env",
        Path.home() / ".env",
        Path.cwd() / ".env",
    ]
    for env_path in candidates:
        if env_path.is_file():
            try:
                for line in env_path.read_text(encoding="utf-8").splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if line.startswith("export "):
                        line = line[7:].strip()
                    if "=" in line:
                        k, v = line.split("=", 1)
                        k = k.strip()
                        v = v.strip().strip("'\"")
                        if k and k not in os.environ:
                            os.environ[k] = v
            except Exception:
                pass


_load_env_fallbacks()


CHAT_CASCADE = [
    {
        "provider": "homelab",
        "model": "agent-coder",
        "url": os.environ.get("HOMELAB_LITELLM_URL", "").rstrip("/") + "/chat/completions",
        "env_key": "HOMELAB_LITELLM_KEY",
    },
    {
        "provider": "openrouter",
        "model": "nvidia/nemotron-3-ultra-550b-a55b:free",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
    },
    {
        "provider": "openrouter",
        "model": "dots-studio/dots-3-note-preview:free",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
    },
    {
        "provider": "openrouter",
        "model": "thinkingmachines/inkling:free",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
    },
    {
        "provider": "openrouter",
        "model": "nvidia/nemotron-3.5-lightning:free",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
    },
    {
        "provider": "openrouter",
        "model": "recursive/flint-v1.0:free",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
    },
    {
        "provider": "openrouter",
        "model": "qwen/qwen-2.5-coder-32b-instruct:free",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
    },
    {
        "provider": "openrouter",
        "model": "openrouter/free",
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "env_key": "OPENROUTER_API_KEY",
    },
    {
        "provider": "gemini",
        "model": "gemini-3.5-flash-lite",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "env_key": "GEMINI_API_KEY",
    },
    {
        "provider": "gemini",
        "model": "gemini-flash-lite-latest",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "env_key": "GEMINI_API_KEY",
    },
    {
        "provider": "gemini",
        "model": "gemini-2.5-flash",
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "env_key": "GEMINI_API_KEY",
    },
]

# JEV models speak OpenRouter's /api/alpha/decisions endpoint (typed noul/choice/score/box).
JEV_DECISION_MODELS = [
    "baseten/mammoth-1:free",   # 27B - heavier reasoning, complex multi-question decisions
    "baseten/elephant-1:free",  # 9B  - fast, simple decisions
    "respan/span-01-lite:free", # lite JEV decision model
    "inception/mercury-decide:free",
]

def _is_jev_model(model: str) -> bool:
    m = (model or "").lower()
    return (
        "mammoth" in m
        or "elephant" in m
        or "respan" in m
        or "span-01" in m
        or "inception" in m
        or "decide" in m
        or m in {x.lower() for x in JEV_DECISION_MODELS}
    )


def _jev_cascade_for(query: str, options: list = None) -> list:
    # Optimise routing: fast 9B for simple/binary, 27B for richer multi-option decisions.
    if options:
        # Respan is noul-only, so exclude it for choice decisions.
        if len(options) >= 3:
            return ["baseten/mammoth-1:free", "baseten/elephant-1:free", "inception/mercury-decide:free"]
        return ["baseten/elephant-1:free", "baseten/mammoth-1:free", "inception/mercury-decide:free"]
    # Binary/no-options: noul-capable models first (respan is lite & fast).
    return ["respan/span-01-lite:free", "baseten/elephant-1:free", "baseten/mammoth-1:free", "inception/mercury-decide:free"]


DECIDE_CASCADE = [
    "baseten/elephant-1:free",
    "baseten/mammoth-1:free",
    "respan/span-01-lite:free",
    "inception/mercury-decide:free",
    "nvidia/nemotron-3.5-lightning:free",
    "openrouter/free",
]

EMBED_CASCADE = [
    "liquid/lfm-2.5-embedding-350m:free",
    "nvidia/llama-nemotron-embed-vl-1b-v2:free",
]

RERANK_CASCADE = [
    "nvidia/llama-nemotron-rerank-vl-1b-v2:free",
]

TTS_CASCADE = [
    "fish-audio/s2.1-pro-free:free",
]

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "run_bash_batch",
            "description": (
                "Execute an ordered sequence of shell commands inside a single compound bash environment. "
                "Commands share working directory context (e.g. `cd dir` affects subsequent commands). "
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


def check_tcp_port(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def apply_response_projection(raw_output: str, project_fields: str = None, jq_expr: str = None) -> str:
    if not raw_output.strip():
        return raw_output

    if jq_expr and shutil.which("jq"):
        try:
            p = subprocess.run(["jq", jq_expr], input=raw_output, text=True, capture_output=True)
            if p.returncode == 0:
                return p.stdout.strip()
        except Exception:
            pass

    if project_fields:
        fields = [f.strip() for f in project_fields.split(",") if f.strip()]
        try:
            data = json.loads(raw_output)
            if isinstance(data, dict):
                filtered = {k: v for k, v in data.items() if k in fields}
                return json.dumps(filtered, indent=2)
            elif isinstance(data, list):
                filtered = [
                    {k: v for k, v in item.items() if k in fields} if isinstance(item, dict) else item
                    for item in data
                ]
                return json.dumps(filtered, indent=2)
        except Exception:
            pass

    return raw_output


def _http_post_json(url: str, payload: dict, api_key: str, timeout: int = 90) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/RooVetGit/Roo-Cline",
            "X-Title": "Roo Code",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def call_llm_with_cascade(messages: list, preferred_model: str = None, enable_tools: bool = False):
    cascade = [c for c in CHAT_CASCADE if c["url"] != "/chat/completions"]
    if preferred_model:
        if "gemini" in preferred_model.lower():
            cascade.insert(
                0,
                {
                    "provider": "gemini",
                    "model": preferred_model,
                    "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
                    "env_key": "GEMINI_API_KEY",
                },
            )
        else:
            cascade.insert(
                0,
                {
                    "provider": "openrouter",
                    "model": preferred_model,
                    "url": "https://openrouter.ai/api/v1/chat/completions",
                    "env_key": "OPENROUTER_API_KEY",
                },
            )

    last_err = None
    for target in cascade:
        api_key = os.environ.get(target["env_key"], "")
        if not api_key:
            continue

        payload = {
            "model": target["model"],
            "messages": messages,
        }
        if enable_tools:
            payload["tools"] = TOOLS
            payload["parallel_tool_calls"] = True

        if target["provider"] == "openrouter":
            payload["provider"] = {
                "require_parameters": True,
                "allow_fallbacks": True,
            }

        try:
            timeout_s = 5 if target["provider"] == "homelab" else 90
            data = _http_post_json(target["url"], payload, api_key, timeout=timeout_s)
            if "error" in data:
                err_msg = data["error"].get("message", str(data["error"]))
                sys.stderr.write(f"[openrouter-free] {target['model']} API Error: {err_msg[:200]}\n")
                last_err = err_msg
                continue

            if "choices" not in data or not data["choices"]:
                sys.stderr.write(f"[openrouter-free] {target['model']} unexpected response: {data}\n")
                last_err = "No choices in response"
                continue

            choice = data["choices"][0]["message"]
            if not choice.get("content") and choice.get("reasoning"):
                choice["content"] = choice["reasoning"]
            return choice, target["model"]
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="ignore")
            try:
                err_json = json.loads(err_body)
                err_msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                err_msg = err_body
            sys.stderr.write(f"[openrouter-free] {target['model']} HTTP {e.code}: {err_msg[:200]}\n")
            last_err = f"HTTP {e.code}: {err_msg[:100]}"
            if e.code in (429, 503):
                time.sleep(2)
                continue
        except Exception as e:
            sys.stderr.write(f"[openrouter-free] {target['model']} error: {e}\n")
            last_err = str(e)

    raise RuntimeError(f"All cascade endpoints exhausted. Last error: {last_err}")


def execute_compound_batch(commands: list, cwd: str = None, timeout_total: int = 180) -> str:
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


def run_agent_loop(prompt: str, preferred_model: str = None, max_turns: int = 12, out_file: str = None):
    system_prompt = (
        "You are an autonomous coding and system verification subagent.\n"
        "You have bash access via `run_bash_batch`.\n"
        "CRITICAL: Always batch multiple commands into single turns to conserve rate limits.\n"
        "Commands in the array share directory context and stop on fatal errors.\n"
        "Inspect files, make minimal necessary edits, verify with tests, and output a concise report.\n\n"
        "Available Workstation & Browser Verification CLIs in PATH:\n"
        "- `fast-cdp verify <url> [--assert-selector <sel>] [--assert-text <txt>] [--screenshot <path>] [--json]`: Sub-second native Chrome DevTools Protocol verification on port :9222.\n"
        "- `fast-cdp snap <url>`: Instant viewport accessibility text snapshot.\n"
        "- `ocr read <file>`: LightOnOCR-3-0.8B document and image OCR.\n"
        "- `jev bool / choice / score`: Calibrated non-generative decisions.\n"
        "- `audiocpp tts / asr`: Speech synthesis and verbatim transcription.\n"
        "- `local-llm \"<prompt>\"`: Local Qwen3.6-35B coder on :8080 (see the `local-llm` skill).\n"
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": prompt},
    ]

    used_model = preferred_model or "auto"
    final_content = ""

    for turn in range(1, max_turns + 1):
        sys.stderr.write(f"\n[Turn {turn}/{max_turns}] Invoking model cascade...\n")
        msg, used_model = call_llm_with_cascade(messages, preferred_model=preferred_model, enable_tools=True)
        messages.append(msg)

        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            final_content = msg.get("content", "")
            print(f"\n--- Subagent Completed via {used_model} in {turn} turn(s) ---")
            print(final_content)
            if out_file:
                Path(out_file).write_text(final_content, encoding="utf-8")
            return final_content

        for tc in tool_calls:
            fn_name = tc.get("function", {}).get("name")
            raw_args = tc.get("function", {}).get("arguments", "{}")
            args = json.loads(raw_args) if isinstance(raw_args, str) else raw_args

            if fn_name == "run_bash_batch":
                cmds = args.get("commands", [])
                sys.stderr.write(f"  [Turn {turn} | {used_model}] Executing batch of {len(cmds)} command(s)...\n")
                output = execute_compound_batch(cmds)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc["id"],
                        "name": fn_name,
                        "content": output,
                    }
                )

    sys.stderr.write(f"\n[openrouter-free] Subagent finished all {max_turns} turns.\n")
    return final_content or (messages[-1].get("content") if messages else "")


def run_single_chat(prompt: str, preferred_model: str = None, out_file: str = None):
    messages = [{"role": "user", "content": prompt}]
    msg, used_model = call_llm_with_cascade(messages, preferred_model=preferred_model, enable_tools=False)
    content = msg.get("content", "")
    res = {"status": "success", "model": used_model, "content": content}
    if out_file:
        Path(out_file).write_text(content, encoding="utf-8")
    return res


_CONF_RE = re.compile(r"\b(?:confidence|probability|score)\b\s*[:=]?\s*([-+]?\d*\.?\d+)", re.I)


def _normalize_verdict(text: str, options: list = None) -> tuple:
    """Split a chatty completion into (verdict, confidence).

    The chat fallback asks for a verdict *with confidence*, so a free endpoint
    answers "yes\\nConfidence: 1.0". Callers comparing against an option need
    "yes", and the confidence is worth keeping rather than discarding.
    """
    confidence = None
    match = _CONF_RE.search(text)
    if match:
        try:
            confidence = float(match.group(1))
        except ValueError:
            confidence = None

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    cleaned = _CONF_RE.sub("", first_line).strip(" \t\"'`.,;:-—*")

    if options:
        choices = sorted((o.strip() for o in options if o and o.strip()), key=len, reverse=True)
        for choice in choices:
            if cleaned.lower() == choice.lower():
                return choice, confidence
        # The option may be mentioned on a different line than the first.
        haystack = _CONF_RE.sub("", text)
        for choice in choices:
            if re.search(rf"(?<![\w-]){re.escape(choice)}(?![\w-])", haystack, re.I):
                return choice, confidence
    return cleaned, confidence


def run_decide(query: str, options: list = None, preferred_model: str = None,
               state: str = None, questions: dict = None):
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for decide mode.")

    # Resolve the JEV candidate list (fast-first or complexity-optimised).
    if preferred_model and _is_jev_model(preferred_model):
        jev_candidates = [preferred_model]
    elif preferred_model:
        jev_candidates = []
    else:
        jev_candidates = _jev_cascade_for(query, options)

    # Build the questions payload (full schema passthrough or derived from query/options).
    effective_state = state or query
    if questions is not None:
        q_payload = questions
    elif options:
        criteria = {opt: "The option '%s' applies to: %s" % (opt, query) for opt in options}
        q_payload = {
            "decision": {
                "type": "choice",
                "instructions": query,
                "criteria": criteria,
            }
        }
    else:
        q_payload = {
            "decision": {
                "type": "noul",
                "instructions": query,
                "criteria": {
                    "true": "The condition or statement holds / is true.",
                    "false": "The condition or statement does not hold / is false.",
                },
            }
        }

    alpha_url = "https://openrouter.ai/api/alpha/decisions"

    def _respan_noul_only(model, qp):
        if "respan" not in (model or "").lower():
            return True
        # Respan only accepts noul questions with plain-string criteria.
        if not isinstance(qp, dict):
            return False
        for q in qp.values():
            if not isinstance(q, dict) or q.get("type") != "noul":
                return False
            crit = q.get("criteria")
            if not isinstance(crit, dict):
                return False
            if not all(isinstance(v, str) for v in crit.values()):
                return False
        return True

    for model in jev_candidates:
        if not _respan_noul_only(model, q_payload):
            sys.stderr.write("[openrouter-free decide] %s skipped (noul-only)\n" % model)
            continue
        try:
            dec_payload = {
                "model": model,
                "state": effective_state,
                "questions": q_payload,
            }
            res = _http_post_json(alpha_url, dec_payload, api_key, timeout=45)
            answers = res.get("answers", {})
            ans = answers.get("decision", {}) if isinstance(answers, dict) else {}
            # Normalise verdict across noul / choice / score / box answer shapes.
            verdict = None
            confidence = ans.get("confidence")
            noul = ans.get("noul")
            if "choice" in ans:
                verdict = ans.get("choice")
            elif noul is not None:
                verdict = "true" if (noul >= 0.5) else "false"
                confidence = confidence if confidence is not None else max(noul, 1.0 - noul)
            elif "score" in ans:
                verdict = ans.get("score")
            else:
                verdict = ans.get("verdict") or ans.get("decision")
            result = {
                "status": "success",
                "model": res.get("model", model),
                "verdict": verdict,
                "probabilities": ans.get("probabilities", {}),
                "confidence": confidence,
                "answers": answers,
                "raw": ans,
            }
            if noul is not None:
                result["noul"] = noul
            return result
        except Exception as e:
            sys.stderr.write("[openrouter-free decide] %s error: %s\n" % (model, str(e)[:200]))
            continue

    # Chat fallback (non-JEV or all JEV endpoints exhausted).
    chat_model = preferred_model if (preferred_model and not _is_jev_model(preferred_model)) else "nvidia/nemotron-3.5-lightning:free"
    prompt_text = query
    if options:
        opts_formatted = "\n".join("- %s" % o for o in options)
        prompt_text = "%s\n\nSelect strictly one of these options:\n%s" % (query, opts_formatted)

    payload = {
        "model": chat_model,
        "messages": [
            {"role": "system", "content": "You are a calibrated zero-shot decision router. Give your verdict with confidence score."},
            {"role": "user", "content": prompt_text},
        ],
        "temperature": 0.0,
    }
    data = _http_post_json("https://openrouter.ai/api/v1/chat/completions", payload, api_key, timeout=45)
    content = data["choices"][0]["message"].get("content", "")
    verdict, confidence = _normalize_verdict(content, options)
    return {
        "status": "success",
        "model": chat_model,
        "verdict": verdict,
        "confidence": confidence,
        "raw_text": content.strip(),
    }

def run_batched_embeddings(inputs: list, preferred_model: str = None, out_json: str = None):
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for embeddings.")

    resolved_texts = []
    for item in inputs:
        p = Path(item)
        if p.is_file():
            resolved_texts.append(p.read_text(errors="ignore")[:8000])
        else:
            resolved_texts.append(item)

    models = ([preferred_model] if preferred_model else []) + [m for m in EMBED_CASCADE if m != preferred_model]
    last_err = None
    for model in models:
        payload = {
            "model": model,
            "input": resolved_texts,
            "provider": {"allow_fallbacks": True},
        }
        try:
            data = _http_post_json("https://openrouter.ai/api/v1/embeddings", payload, api_key, timeout=60)
            vectors = [
                {
                    "index": idx,
                    "source": inputs[idx],
                    "dimensions": len(row["embedding"]),
                    "embedding": row["embedding"],
                }
                for idx, row in enumerate(data.get("data", []))
            ]
            result = {"status": "success", "model": model, "count": len(vectors), "results": vectors}
            if out_json:
                Path(out_json).write_text(json.dumps(result, indent=2), encoding="utf-8")
            return {
                "status": "success",
                "model": model,
                "count": len(vectors),
                "dimensions": vectors[0]["dimensions"] if vectors else 0,
                "saved_to": out_json,
                "preview_dims": vectors[0]["embedding"][:5] if vectors else [],
            }
        except Exception as e:
            sys.stderr.write(f"[openrouter-free embed] {model} error: {e}\n")
            last_err = e

    raise RuntimeError(f"All free embedding endpoints failed: {last_err}")


def run_tts(text: str, out_path: str = "output.mp3", preferred_model: str = None):
    api_key = os.environ.get("OPENROUTER_API_KEY", "")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is required for TTS.")

    models = ([preferred_model] if preferred_model else []) + [m for m in TTS_CASCADE if m != preferred_model]
    last_err = None
    for model in models:
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/audio/speech",
                data=json.dumps({"model": model, "input": text, "voice": "alloy"}).encode("utf-8"),
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                    "HTTP-Referer": "https://github.com/local-agent-harness",
                    "X-Title": "openrouter-free-skill",
                },
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw_bytes = resp.read()
                Path(out_path).write_bytes(raw_bytes)
                return {"status": "success", "model": model, "saved_path": out_path, "bytes": len(raw_bytes)}
        except Exception:
            try:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": text}],
                    "modalities": ["text", "audio"],
                    "audio": {"voice": "alloy", "format": "mp3"},
                }
                data = _http_post_json("https://openrouter.ai/api/v1/chat/completions", payload, api_key, timeout=60)
                msg = data["choices"][0]["message"]
                audio_b64 = msg.get("audio", {}).get("data")
                if audio_b64:
                    Path(out_path).write_bytes(base64.b64decode(audio_b64))
                    return {"status": "success", "model": model, "saved_path": out_path, "bytes": len(audio_b64)}
            except Exception as e2:
                sys.stderr.write(f"[openrouter-free tts] {model} error: {e2}\n")
                last_err = e2

    raise RuntimeError(f"All free TTS endpoints failed: {last_err}")


def run_multi_pipeline(chat_prompt: str = None, embed_inputs: list = None, tts_text: str = None, tts_out: str = "output.mp3", model: str = None):
    summary = {}
    if chat_prompt:
        try:
            summary["chat"] = run_single_chat(chat_prompt, preferred_model=model)
        except Exception as e:
            summary["chat"] = {"status": "error", "error": str(e)}

    if embed_inputs:
        try:
            summary["embed"] = run_batched_embeddings(embed_inputs)
        except Exception as e:
            summary["embed"] = {"status": "error", "error": str(e)}

    if tts_text:
        try:
            summary["tts"] = run_tts(tts_text, out_path=tts_out)
        except Exception as e:
            summary["tts"] = {"status": "error", "error": str(e)}

    return summary


def run_doctor(as_json: bool = False, live_probe: bool = False) -> int:
    or_key = os.environ.get("OPENROUTER_API_KEY", "")
    gemini_key = os.environ.get("GEMINI_API_KEY", "")
    homelab_url = os.environ.get("HOMELAB_LITELLM_URL", "")

    auth_info = {}
    auth_ok = False
    auth_error = None

    if or_key:
        try:
            req = urllib.request.Request(
                "https://openrouter.ai/api/v1/auth/key",
                headers={
                    "Authorization": f"Bearer {or_key}",
                    "HTTP-Referer": "https://github.com/RooVetGit/Roo-Cline",
                    "X-Title": "openrouter-free-doctor",
                },
            )
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                auth_info = data.get("data", {})
                auth_ok = True
        except Exception as e:
            auth_error = str(e)
    else:
        auth_error = "OPENROUTER_API_KEY not found in environment or .agent_keys.env"

    daily_reqs = auth_info.get("free_model_daily_requests", {})
    daily_remaining = daily_reqs.get("remaining")
    daily_limit = daily_reqs.get("limit")
    daily_used = daily_reqs.get("used")

    local_services = {
        "genesis_35b_8080": check_tcp_port("127.0.0.1", 8080),
        "litellm_gateway_4000": check_tcp_port("127.0.0.1", 4000),
        "h2o_jev_8083": check_tcp_port("127.0.0.1", 8083),
        "fast_cdp_9222": check_tcp_port("127.0.0.1", 9222),
    }

    live_results = {}
    if live_probe and auth_ok:
        t0 = time.time()
        try:
            dec_res = run_decide("Is 2+2=4?", options=["yes", "no"], preferred_model="baseten/elephant-1:free")
            live_results["elephant_jev"] = {
                "status": "online",
                "verdict": dec_res.get("verdict"),
                "latency_ms": int((time.time() - t0) * 1000),
            }
        except Exception as e:
            live_results["elephant_jev"] = {"status": "error", "error": str(e)}

        t0 = time.time()
        try:
            dec_res = run_decide("Is 2+2=4?", options=["yes", "no"], preferred_model="baseten/mammoth-1:free")
            live_results["mammoth_jev"] = {
                "status": "online",
                "verdict": dec_res.get("verdict"),
                "latency_ms": int((time.time() - t0) * 1000),
            }
        except Exception as e:
            live_results["mammoth_jev"] = {"status": "error", "error": str(e)}

        t0 = time.time()
        try:
            dec_res = run_decide("Is 2+2=4?", preferred_model="respan/span-01-lite:free")
            live_results["respan_jev"] = {
                "status": "online",
                "verdict": dec_res.get("verdict"),
                "latency_ms": int((time.time() - t0) * 1000),
            }
        except Exception as e:
            live_results["respan_jev"] = {"status": "error", "error": str(e)}

    status_str = "HEALTHY" if auth_ok else "UNHEALTHY"

    report = {
        "status": status_str,
        "credentials": {
            "openrouter_api_key": {
                "configured": bool(or_key),
                "valid": auth_ok,
                "label": auth_info.get("label"),
                "expires_at": auth_info.get("expires_at"),
                "error": auth_error,
            },
            "gemini_api_key": {
                "configured": bool(gemini_key),
            },
            "homelab_litellm_url": {
                "configured": bool(homelab_url),
                "url": homelab_url or None,
            },
        },
        "free_tier_telemetry": {
            "daily_requests_remaining": daily_remaining,
            "daily_requests_limit": daily_limit,
            "daily_requests_used": daily_used,
            "rate_limit": auth_info.get("rate_limit", {}),
        },
        "local_homelab_fallbacks": local_services,
        "live_probe": live_results if live_probe else "omitted (use --live to probe)",
    }

    if as_json:
        print(json.dumps(report, indent=2))
    else:
        print(f"\n🩺 [openrouter-free] Diagnostic Health Check")
        print("  " + "─" * 55)
        if auth_ok:
            print(f"  • OpenRouter API Key:  ✅ VALID ({auth_info.get('label')})")
            print(f"  • Daily Free Quota:    {daily_remaining}/{daily_limit} remaining (Used: {daily_used})")
            print(f"  • Key Expiration:      {auth_info.get('expires_at')}")
        else:
            print(f"  • OpenRouter API Key:  ❌ INVALID / MISSING ({auth_error})")

        print(f"  • Gemini Fallback:     {'✅ Configured' if gemini_key else '⚠️  Not set (optional)'}")
        print(f"  • Homelab Fallback:    {'✅ ' + homelab_url if homelab_url else 'ℹ️  Direct local hardware priority'}")

        print("\n  🖥️  Local Inference Headroom (Homelab Priority):")
        print(f"  • Genesis 35B (:8080):  {'✅ ONLINE' if local_services['genesis_35b_8080'] else '⚪ OFFLINE'}")
        print(f"  • LiteLLM Gate (:4000): {'✅ ONLINE' if local_services['litellm_gateway_4000'] else '⚪ OFFLINE'}")
        print(f"  • h2o-lightning-4b JEV (:8083):{'✅ ONLINE' if local_services['h2o_jev_8083'] else '⚪ OFFLINE'}")
        print(f"  • Fast-CDP (:9222):     {'✅ ONLINE' if local_services['fast_cdp_9222'] else '⚪ OFFLINE'}")

        if live_probe:
            print("\n  ⚡ Live Inference Probes:")
            for m_name, res in live_results.items():
                st = res.get("status", "unknown").upper()
                lat = f" ({res.get('latency_ms')}ms)" if "latency_ms" in res else ""
                print(f"  • {m_name:<20} {st}{lat}")

        print(f"\n  Overall Status: {'✅ OPERATIONAL' if auth_ok else '❌ ACTION REQUIRED'}\n")

    return 0 if auth_ok else 1


def main():
    parser = argparse.ArgumentParser(description="OpenRouter Free Multimodal & Subagent CLI (Uber Protocol)")
    sub = parser.add_subparsers(dest="mode", required=True)

    p_agent = sub.add_parser("agent", help="Run autonomous subagent loop with compound bash batching")
    p_agent.add_argument("--prompt", required=True, help="Task instructions")
    p_agent.add_argument("--model", default=None, help="Specific model override")
    p_agent.add_argument("--max-turns", type=int, metavar="LIMIT", default=12, help="Maximum conversation turns")
    p_agent.add_argument("--out", default=None, help="Save final subagent report to file")

    p_chat = sub.add_parser("chat", help="Single-turn completion or code review")
    p_chat.add_argument("--prompt", required=True, help="Prompt text or diff")
    p_chat.add_argument("--model", default=None, help="Specific model override")
    p_chat.add_argument("--out", default=None, help="Save output to file")
    p_chat.add_argument("--project", default=None, help="Comma-separated fields to project")
    p_chat.add_argument("--jq", default=None, help="JQ filter expression")

    p_decide = sub.add_parser("decide", help="Calibrated decision routing (JEV: mammoth/elephant/mercury)")
    p_decide.add_argument("--query", required=True, help="Question or routing prompt (also used as state if --state omitted)")
    p_decide.add_argument("--options", nargs="*", default=None, help="List of candidate options")
    p_decide.add_argument("--model", default=None, help="Specific model override")
    p_decide.add_argument("--state", default=None, help="State text for the decision (defaults to --query)")
    p_decide.add_argument("--questions-json", default=None, help="Full questions object as JSON or @file (multi-question JEV)")
    p_decide.add_argument("--out", default=None, help="Save output to file")
    p_decide.add_argument("--project", default=None, help="Comma-separated fields to project")
    p_decide.add_argument("--jq", default=None, help="JQ filter expression")

    p_embed = sub.add_parser("embed", help="Batched embeddings (LFM / Nemotron Embed)")
    p_embed.add_argument("--inputs", nargs="+", required=True, help="Texts or file paths")
    p_embed.add_argument("--model", default=None, help="Specific model override")
    p_embed.add_argument("--out-json", default=None, help="Save full embedding vectors to JSON file")
    p_embed.add_argument("--out", default=None, help="Save output summary to file")
    p_embed.add_argument("--project", default=None, help="Comma-separated fields to project")
    p_embed.add_argument("--jq", default=None, help="JQ filter expression")

    p_tts = sub.add_parser("tts", help="Generate speech audio (Fish Audio Free)")
    p_tts.add_argument("--text", required=True, help="Text to speak")
    p_tts.add_argument("--out", default="output.mp3", help="Output MP3 path")
    p_tts.add_argument("--model", default=None, help="Specific model override")
    p_tts.add_argument("--project", default=None, help="Comma-separated fields to project")
    p_tts.add_argument("--jq", default=None, help="JQ filter expression")

    p_multi = sub.add_parser("multi", help="Execute multi-modal pipeline without concurrency lock")
    p_multi.add_argument("--chat", default=None, help="Prompt for chat")
    p_multi.add_argument("--embed", nargs="*", default=None, help="Inputs to embed")
    p_multi.add_argument("--tts", default=None, help="Text to speak")
    p_multi.add_argument("--tts-out", default="output.mp3", help="Output audio file")
    p_multi.add_argument("--model", default=None, help="Chat model override")
    p_multi.add_argument("--out", default=None, help="Save summary output to file")
    p_multi.add_argument("--project", default=None, help="Comma-separated fields to project")
    p_multi.add_argument("--jq", default=None, help="JQ filter expression")

    p_doc = sub.add_parser("doctor", aliases=["health"], help="Diagnostic health check of OpenRouter credentials & free tiers")
    p_doc.add_argument("--json", action="store_true", help="Output health report as JSON")
    p_doc.add_argument("--live", action="store_true", help="Run live inference probe to verified free endpoints")

    args = parser.parse_args()

    try:
        if args.mode == "agent":
            run_agent_loop(args.prompt, args.model, args.max_turns, args.out)
            sys.exit(0)
        elif args.mode == "chat":
            raw = json.dumps(run_single_chat(args.prompt, args.model, args.out), indent=2)
            out = apply_response_projection(raw, args.project, args.jq)
            print(out)
            sys.exit(0)
        elif args.mode == "decide":
            questions = None
            if args.questions_json:
                qstr = args.questions_json
                if qstr.startswith("@"):
                    qstr = Path(qstr[1:]).read_text(encoding="utf-8")
                questions = json.loads(qstr)
            raw = json.dumps(run_decide(args.query, args.options, args.model, state=args.state, questions=questions), indent=2)
            out = apply_response_projection(raw, args.project, args.jq)
            if args.out:
                Path(args.out).write_text(out, encoding="utf-8")
            print(out)
            sys.exit(0)
        elif args.mode == "embed":
            raw = json.dumps(run_batched_embeddings(args.inputs, args.model, args.out_json), indent=2)
            out = apply_response_projection(raw, args.project, args.jq)
            if args.out:
                Path(args.out).write_text(out, encoding="utf-8")
            print(out)
            sys.exit(0)
        elif args.mode == "tts":
            raw = json.dumps(run_tts(args.text, args.out, args.model), indent=2)
            out = apply_response_projection(raw, args.project, args.jq)
            print(out)
            sys.exit(0)
        elif args.mode == "multi":
            raw = json.dumps(run_multi_pipeline(args.chat, args.embed, args.tts, args.tts_out, args.model), indent=2)
            out = apply_response_projection(raw, args.project, args.jq)
            if args.out:
                Path(args.out).write_text(out, encoding="utf-8")
            print(out)
            sys.exit(0)
        elif args.mode in ("doctor", "health"):
            code = run_doctor(as_json=args.json, live_probe=args.live)
            sys.exit(code)
    except Exception as e:
        sys.stderr.write(f"❌ Error: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
