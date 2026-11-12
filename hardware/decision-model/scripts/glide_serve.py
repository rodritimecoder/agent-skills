#!/usr/bin/env python3
"""glide_serve — System One decision API for Fastino GLiDE GGUF checkpoints.

GLiDE is an encoder (ModernBERT) plus a 255-way decision readout. llama.cpp
loads and runs the encoder, but the readout lives outside the GGUF: it is a
separate 255x1024 bf16 tensor (`readout.safetensors` in the HF repository) that
is applied to the hidden state of the last real token, right before [SEP].
llama.cpp has no `modern-bert.decision.type` for GLiDE, so a stock llama-server
answers "This model is not a decision model" on /v1/systemone.

This shim supplies the missing half:

    client --/v1/systemone--> glide_serve --/tokenize + /embedding--> llama-server
                                   |
                                   +-- readout matmul + softmax

The wire contract is the one of Fastino's own server (`python -m glide.server`):
`state`, `questions`, and answers that carry `choice` / `noul` / `score` plus
`probabilities` and `confidence`. Prompts, option rendering and truncation
follow glide/prompt.py and glide/encoder.py from fastino/GLiDE-0.4B.

    glide_serve                          # :8083 decision slot, backend :8624
    glide_serve --status | --stop
    glide_serve --port 8083 --restart
"""
from __future__ import annotations

import argparse
import json
import os
import signal
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from array import array
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DRIVE = Path("/run/media/rodri/AI")
DEFAULT_MODEL_DIR = DRIVE / "models/irdor/GLiDE-0.4B-Q8_0-GGUF"
DEFAULT_MODEL = "glide-0.4b-q8_0.gguf"
DEFAULT_SERVER = DRIVE / "llama.cpp/build-vulkan/bin/llama-server"
DEFAULT_PORT = 8083
DEFAULT_BACKEND_PORT = 8624
MAX_OPTIONS = 255
ANSWER_CUE = "Answer: ("
BODY_TAIL = "\n\nThink it through briefly, then answer with the option letter only."

# the tokenizer of the checkpoint is the encoder tokenizer: [CLS] ids [SEP]
DEFAULT_CLS_ID = 50281
DEFAULT_SEP_ID = 50282


# ---------------------------------------------------------------- readout ----

def load_readout(path: Path) -> list[tuple[float, ...]]:
    """readout.safetensors -> 255 rows of 1024 floats (bf16 decoded)."""
    with path.open("rb") as handle:
        header_len = struct.unpack("<Q", handle.read(8))[0]
        header = json.loads(handle.read(header_len))
        start = 8 + header_len
        info = header["weight"]
        if info["dtype"] not in ("BF16", "F16", "F32"):
            raise SystemExit(f"{path}: unsupported readout dtype {info['dtype']}")
        rows, cols = info["shape"]
        begin, end = info["data_offsets"]
        handle.seek(start + begin)
        raw = handle.read(end - begin)
    if info["dtype"] == "BF16":
        halves = array("H")
        halves.frombytes(raw)
        if sys.byteorder == "little":
            packed = array("I", (h << 16 for h in halves))
        else:
            packed = array("I", (int.from_bytes(struct.pack("<H", h), "little") << 16 for h in halves))
        values = memoryview(packed.tobytes()).cast("f")
    elif info["dtype"] == "F16":
        half = array("e")
        half.frombytes(raw)
        values = array("f", half)
    else:
        values = array("f")
        values.frombytes(raw)
    return [tuple(values[i * cols:(i + 1) * cols]) for i in range(rows)]


# ----------------------------------------------------------------- prompt ----

def as_text(value) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return "\n".join(
            f"{k}: {v if isinstance(v, str) else json.dumps(v, ensure_ascii=False)}"
            for k, v in value.items()
        )
    return json.dumps(value, ensure_ascii=False)


def options_for(question: dict) -> list[tuple[str, str]]:
    kind = question.get("type")
    criteria = question.get("criteria") or {}
    if kind == "noul":
        crit = criteria if isinstance(criteria, dict) else {}
        return [("true", crit.get("true") or "Yes"), ("false", crit.get("false") or "No")]
    if kind == "score":
        if isinstance(criteria, list):
            levels = criteria
        elif isinstance(criteria, dict):
            try:
                levels = [criteria[k] for k in sorted(criteria, key=lambda x: float(x))]
            except (TypeError, ValueError):
                raise ValueError("score criteria keys must be numeric levels") from None
        else:
            raise ValueError("score criteria must be a list or an object keyed by numeric level")
        if not levels:
            raise ValueError("a score question needs at least one level")
        return [(str(i), str(level)) for i, level in enumerate(levels)]
    if not isinstance(criteria, dict) or not criteria:
        raise ValueError("a choice question needs a non-empty criteria object")
    return [
        (key, value if isinstance(value, str) and value else
         (json.dumps(value, ensure_ascii=False) if value not in (None, "") else key))
        for key, value in criteria.items()
    ]


def render_prompt(state_text: str, instructions: str, options: list[tuple[str, str]],
                  codes: list[str]) -> str:
    lines = [
        f"({code}) {key}" if description == key else f"({code}) {key}: {description}"
        for code, (key, description) in zip(codes, options)
    ]
    body = (
        f"Context:\n{state_text}\n\nQuestion: {instructions}\n\nOptions:\n"
        + "\n".join(lines)
    ).rstrip() + BODY_TAIL
    # render_tokenizer chat template, reasoning_effort=medium, add_generation_prompt
    return (
        "<|im_start|>user\n" + body + "<|im_end|>\n"
        "<|im_start|>assistant\n<think>\n\n</think>\n\n" + ANSWER_CUE
    )


def softmax(values: list[float]) -> list[float]:
    top = max(values)
    exps = [pow(2.718281828459045, v - top) for v in values]
    total = sum(exps)
    return [v / total for v in exps]


# ----------------------------------------------------------------- shim -----

class Glide:
    def __init__(self, args) -> None:
        self.args = args
        self.model_dir = Path(args.model_dir)
        self.model = Path(args.model) if args.model else self.model_dir / DEFAULT_MODEL
        self.readout_path = Path(args.readout) if args.readout else self.model_dir / "readout.safetensors"
        self.config_path = Path(args.config) if args.config else self.model_dir / "decision_config.json"
        self.codes: list[str] = []
        self.max_len = 7999
        self.trunc_head = 1024
        self.readout: list[tuple[float, ...]] = []
        self.backend = f"http://127.0.0.1:{args.backend_port}"
        self.process: subprocess.Popen | None = None
        self.lock = threading.Lock()

    # -- setup ---------------------------------------------------------------
    def load(self) -> None:
        if not self.model.is_file():
            raise SystemExit(f"missing model: {self.model}")
        if not self.readout_path.is_file():
            raise SystemExit(
                f"missing readout: {self.readout_path}\n"
                "  curl -L -o '<dir>/readout.safetensors' "
                "https://huggingface.co/fastino/GLiDE-0.4B/resolve/main/readout.safetensors"
            )
        config = json.loads(self.config_path.read_text()) if self.config_path.is_file() else {}
        self.codes = config.get("codes") or [chr(65 + i) for i in range(MAX_OPTIONS)]
        self.max_len = int(config.get("max_len", self.max_len))
        self.trunc_head = int(config.get("trunc_head", self.trunc_head))
        self.readout = load_readout(self.readout_path)

    def start_backend(self) -> None:
        server = Path(self.args.server)
        if not server.is_file():
            raise SystemExit(f"missing llama-server: {server}")
        ctx = str(self.args.ctx)
        command = [
            str(server),
            "-m", str(self.model),
            "--embeddings", "--pooling", "none",
            "--host", "127.0.0.1", "--port", str(self.args.backend_port),
            "-ngl", str(self.args.ngl),
            "-c", ctx, "-b", ctx, "-ub", ctx, "-np", "1",
            "--no-ui",
        ]
        device = (self.args.device or "").strip().lower()
        if int(self.args.ngl) == 0 or device == "none":
            # RAM only: -ngl 0 alone still lets the Vulkan backend reserve its
            # compute buffer and run host ops on the card; this turns that off.
            command += ["--device", "none", "--no-op-offload"]
        elif device and device != "all":
            command += ["--device", self.args.device]
        log = Path(self.args.log)
        log.parent.mkdir(parents=True, exist_ok=True)
        handle = log.open("ab")
        self.process = subprocess.Popen(command, stdout=handle, stderr=subprocess.STDOUT,
                                        start_new_session=True)
        deadline = time.time() + 120
        while time.time() < deadline:
            if self.process.poll() is not None:
                raise SystemExit(f"llama-server exited ({self.process.returncode}); see {log}")
            if self.health(self.args.backend_port):
                print(f"backend ready: {self.backend} (ngl={self.args.ngl}, ctx={ctx})")
                return
            time.sleep(0.3)
        raise SystemExit(f"llama-server did not become healthy; see {log}")

    @staticmethod
    def health(port: int) -> bool:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=1) as response:
                return response.status == 200
        except (urllib.error.URLError, OSError):
            return False

    # -- backend calls -------------------------------------------------------
    def call(self, path: str, payload: dict, timeout: float = 120.0):
        request = urllib.request.Request(
            self.backend + path,
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.load(response)

    def tokenize(self, text: str) -> list[int]:
        return self.call("/tokenize", {"content": text, "add_special": False,
                                      "parse_special": True})["tokens"]

    def embedding(self, ids: list[int]) -> list[list[float]]:
        response = self.call("/embedding", {"content": ids})
        return response[0]["embedding"]

    def readout_scores(self, hidden: tuple[float, ...] | list[float], count: int) -> list[float]:
        return [sum(map(float.__mul__, row, hidden)) for row in self.readout[:count]]

    # -- decision ------------------------------------------------------------
    def answer(self, state, question: dict) -> dict:
        kind = question.get("type")
        if kind not in ("choice", "noul", "score"):
            raise ValueError(f"unsupported question type {kind!r} (expected choice, noul or score)")
        options = options_for(question)
        if len(options) > MAX_OPTIONS:
            raise ValueError(f"options per choice exceeds the label set ({len(options)} > {MAX_OPTIONS})")
        state_text = state if isinstance(state, str) else json.dumps(state, ensure_ascii=False)
        prompt = render_prompt(state_text, as_text(question.get("instructions", "")), options, self.codes)

        ids = self.tokenize(prompt)
        room = self.max_len - 2
        if len(ids) > room:
            ids = ids[: self.trunc_head] + ids[len(ids) - (room - self.trunc_head):]
        tokens = [self.args.cls_id] + ids + [self.args.sep_id]

        vectors = self.embedding(tokens)
        if len(vectors) != len(tokens):
            raise RuntimeError(f"backend returned {len(vectors)} vectors for {len(tokens)} tokens")
        hidden = vectors[-2]                       # pooling "last", before [SEP]
        probabilities = softmax(self.readout_scores(hidden, len(options)))

        answer: dict = {"type": kind}
        if kind == "noul":
            p_true = probabilities[0]
            answer.update({"noul": p_true, "confidence": abs(2 * p_true - 1)})
        elif kind == "score":
            order = sorted(probabilities, reverse=True)
            confidence = order[0] - order[1] if len(order) > 1 else 1.0
            answer.update({
                "score": max(range(len(probabilities)), key=probabilities.__getitem__),
                "expected_level": sum(i * p for i, p in enumerate(probabilities)),
                "confidence": confidence,
                "probabilities": {str(i): p for i, p in enumerate(probabilities)},
            })
        else:
            order = sorted(probabilities, reverse=True)
            confidence = order[0] - order[1] if len(order) > 1 else 1.0
            answer.update({
                "choice": options[probabilities.index(max(probabilities))][0],
                "confidence": confidence,
                "probabilities": {key: p for (key, _), p in zip(options, probabilities)},
            })
        answer["_tokens"] = len(tokens)
        return answer

    def decide(self, body: dict) -> dict:
        if "state" not in body:
            raise ValueError("missing 'state'")
        if body.get("files") or body.get("images"):
            raise ValueError("images are not supported by this deployment")
        questions = body.get("questions", {})
        if not isinstance(questions, dict):
            raise ValueError("'questions' must be an object")
        started = time.perf_counter()
        answers = {}
        tokens = 0
        for key, question in questions.items():
            if not isinstance(question, dict):
                raise ValueError("each question must be an object")
            with self.lock:
                answer = self.answer(body["state"], question)
            tokens += answer.pop("_tokens")
            answers[key] = answer
        return {
            "model": self.args.model_name,
            "answers": answers,
            "usage": {"input_tokens": tokens, "output_tokens": 0},
            "latency_ms": round((time.perf_counter() - started) * 1000.0, 2),
        }


# ----------------------------------------------------------------- http -----

def make_handler(glide: Glide):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, fmt, *args):  # keep the console quiet
            pass

        def send_json(self, status: int, payload: dict) -> None:
            data = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path in ("/health", "/health/"):
                self.send_json(200, {
                    "status": "ok",
                    "model": glide.args.model_name,
                    "backend": glide.backend,
                    "readout": str(glide.readout_path),
                })
            elif self.path in ("/v1/models", "/models"):
                self.send_json(200, {
                    "object": "list",
                    "data": [{
                        "id": glide.args.model_name,
                        "object": "model",
                        "created": int(time.time()),
                        "owned_by": "llamacpp",
                        "architecture": {
                            "input_modalities": ["text"],
                            "output_modalities": ["decisions"],
                        },
                    }],
                })
            else:
                self.send_json(404, {"error": "not found"})

        def do_POST(self):
            length = int(self.headers.get("Content-Length") or 0)
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
            except json.JSONDecodeError as exc:
                self.send_json(400, {"error": f"invalid JSON: {exc}"})
                return
            if self.path.rstrip("/") != "/v1/systemone":
                self.send_json(404, {"error": "not found"})
                return
            try:
                self.send_json(200, glide.decide(body))
            except ValueError as exc:
                self.send_json(422, {"error": str(exc)})
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode(errors="replace")[:500]
                self.send_json(502, {"error": f"backend HTTP {exc.code}: {detail}"})
            except (urllib.error.URLError, TimeoutError) as exc:
                self.send_json(504, {"error": f"backend unavailable: {exc}"})
            except Exception as exc:                    # noqa: BLE001 - report, never crash
                self.send_json(500, {"error": f"{type(exc).__name__}: {exc}"})

    return Handler


# ----------------------------------------------------------------- main -----

def port_pids(port: int) -> list[int]:
    output = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True).stdout
    return [int(value) for value in output.split() if value.strip().isdigit()]


def stop(ports: list[int]) -> None:
    for port in ports:
        for pid in port_pids(port):
            try:
                os.kill(pid, signal.SIGTERM)
                print(f"stopped pid {pid} on :{port}")
            except ProcessLookupError:
                pass


def main() -> int:
    parser = argparse.ArgumentParser(description="GLiDE decision API (System One over a llama.cpp encoder)")
    parser.add_argument("--model-dir", default=os.environ.get("GLIDE_MODEL_DIR", str(DEFAULT_MODEL_DIR)))
    parser.add_argument("--model", default=os.environ.get("GLIDE_MODEL"))
    parser.add_argument("--readout", default=os.environ.get("GLIDE_READOUT"))
    parser.add_argument("--config", default=os.environ.get("GLIDE_CONFIG"))
    parser.add_argument("--server", default=os.environ.get("GLIDE_SERVER", str(DEFAULT_SERVER)))
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", DEFAULT_PORT)))
    parser.add_argument("--backend-port", type=int,
                        default=int(os.environ.get("GLIDE_BACKEND_PORT", DEFAULT_BACKEND_PORT)))
    parser.add_argument("--ngl", default=os.environ.get("GLIDE_NGL", "99"))
    parser.add_argument("--ctx", type=int, default=int(os.environ.get("GLIDE_CTX", "8192")))
    # One GPU. Splitting a 400 MB encoder over two Vulkan devices makes each split
    # reserve its own copy of the full-batch attention graph: 3.6 GB instead of 1.0.
    parser.add_argument("--device", default=os.environ.get("GLIDE_DEVICE", "Vulkan0"))
    parser.add_argument("--model-name", default=os.environ.get("GLIDE_MODEL_NAME", "glide-0.4b"))
    parser.add_argument("--cls-id", type=int, default=int(os.environ.get("GLIDE_CLS_ID", DEFAULT_CLS_ID)))
    parser.add_argument("--sep-id", type=int, default=int(os.environ.get("GLIDE_SEP_ID", DEFAULT_SEP_ID)))
    parser.add_argument("--log", default=os.environ.get("GLIDE_LOG", "/tmp/opencode/glide-backend.log"))
    parser.add_argument("--restart", action="store_true", help="stop whatever holds the ports first")
    parser.add_argument("--status", action="store_true", help="report whether the slot is up")
    parser.add_argument("--stop", action="store_true", help="stop the shim and its backend")
    args = parser.parse_args()

    if args.status:
        for port in (args.port, args.backend_port):
            state = "UP" if Glide.health(port) else "DOWN"
            print(f":{port} {state}")
        return 0
    if args.stop:
        stop([args.port, args.backend_port])
        return 0

    if args.restart:
        stop([args.port, args.backend_port])
    elif Glide.health(args.port):
        print(f":{args.port} is already serving — pass --restart to replace it")
        return 1

    glide = Glide(args)
    glide.load()
    glide.start_backend()

    httpd = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(glide))
    httpd.daemon_threads = True
    print(f"GLiDE decision API on http://127.0.0.1:{args.port}  "
          f"(POST /v1/systemone, backend {glide.backend}, readout {len(glide.readout)}x"
          f"{len(glide.readout[0]) if glide.readout else 0})")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        if glide.process is not None:
            glide.process.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
