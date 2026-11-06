#!/usr/bin/env python3
"""h2o-serve — start the h2o-lightning decision + box API.

The box question is served by h2oai's shim, not by llama.cpp's own
`/v1/systemone` (which answers choice, noul and score only). The shim needs two
things this launcher guarantees: a Python with Pillow — without it every box
comes back `confidence: 0.0` because the tightness readout is skipped — and a
llama.cpp backend at the pinned revision.

    h2o-serve                      # CPU backend, Q8_0, box enabled
    h2o-serve --backend vulkan     # build and use the pinned Vulkan backend (AMD)
    h2o-serve --backend cuda --gpu 1
    h2o-serve --status | --stop

Front API on :8761, private backend on :8621, both loopback.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO = "h2oai/h2o-lightning-4b-gguf"
BOOTSTRAP_REVISION = "c6746fb6939a76a486ef6e7eb1310ef5d6bb073f"
BOOTSTRAP_SHA256 = "a6def17a598453932e552af41d3ffdff619c50af014e18c3c010aaf0c5efa2fb"
PINNED_LLAMACPP = "10a60cf303566e10d6a7a2774c17d2085503d87b"
VARIANTS = ("Q8_0", "Q5_K_M", "Q4_K_M", "BF16", "mixed-IQ3_XXS", "IQ3_XXS", "IQ2_XXS", "IQ1_M")
DEFAULT_PORT = 8761
DEFAULT_BACKEND_PORT = 8621
DEFAULT_CACHE = Path.home() / ".cache" / "h2o_lightning_gguf"
VENV = Path(os.environ.get("H2O_VENV", Path.home() / ".local/share/h2o-lightning/venv"))
BOOTSTRAP = Path(os.environ.get("H2O_BOOTSTRAP", Path.home() / ".cache/h2o-lightning/bootstrap.py"))


def health(port: int, timeout: float = 2.0) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=timeout) as response:
            return response.status == 200
    except (urllib.error.URLError, OSError):
        return False


def port_pids(port: int) -> list[int]:
    try:
        out = subprocess.run(["lsof", "-ti", f"tcp:{port}"], capture_output=True, text=True).stdout
    except FileNotFoundError:
        return []
    return [int(x) for x in out.split() if x.strip().isdigit()]


def stop(port: int, backend_port: int) -> None:
    killed = False
    for target in (port, backend_port):
        for pid in port_pids(target):
            try:
                os.kill(pid, signal.SIGTERM)
                killed = True
                print(f"stopped pid {pid} on :{target}")
            except ProcessLookupError:
                pass
    if not killed:
        print("nothing listening")


def python_ok(python: Path) -> bool:
    if not python.is_file():
        return False
    probe = subprocess.run([str(python), "-c", "import huggingface_hub, PIL"], capture_output=True)
    return probe.returncode == 0


def ensure_python() -> Path:
    python = VENV / "bin" / "python"
    if python_ok(python):
        return python
    print(f"preparing {VENV} (huggingface_hub + pillow)")
    VENV.parent.mkdir(parents=True, exist_ok=True)
    uv = shutil.which("uv")
    if uv:
        subprocess.run([uv, "venv", "--python", "3.14", str(VENV)], check=True)
        subprocess.run([uv, "pip", "install", "--python", str(python), "huggingface_hub", "pillow"], check=True, capture_output=True)
    else:
        subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        subprocess.run([str(python), "-m", "pip", "install", "--quiet", "huggingface_hub", "pillow"], check=True)
    if not python_ok(python):
        raise SystemExit("h2o-serve: could not build a Python with huggingface_hub + Pillow")
    return python


def ensure_bootstrap() -> Path:
    if BOOTSTRAP.is_file() and hashlib.sha256(BOOTSTRAP.read_bytes()).hexdigest() == BOOTSTRAP_SHA256:
        return BOOTSTRAP
    BOOTSTRAP.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://huggingface.co/{REPO}/raw/{BOOTSTRAP_REVISION}/bootstrap.py"
    with urllib.request.urlopen(url, timeout=120) as response:
        blob = response.read()
    digest = hashlib.sha256(blob).hexdigest()
    if digest != BOOTSTRAP_SHA256:
        raise SystemExit(f"h2o-serve: bootstrap.py hash {digest} does not match the published pin")
    BOOTSTRAP.write_bytes(blob)
    return BOOTSTRAP


def prepare(python: Path, args) -> dict:
    command = [
        str(python), str(ensure_bootstrap()),
        "--backend", "cpu" if args.backend == "vulkan" else args.backend,
        "--variant", args.variant,
        "--cache", str(args.cache),
        "--prepare-only",
    ]
    if args.images:
        command.append("--images")
    if args.backend == "cuda":
        command += ["--gpu", args.gpu]
    run = subprocess.run(command, capture_output=True, text=True)
    if run.returncode != 0:
        sys.stderr.write(run.stderr[-2000:])
        raise SystemExit("h2o-serve: preparing the verified runtime failed")
    proof = json.loads(run.stdout[run.stdout.index("{"):])
    return proof


def vulkan_cmake_args() -> list[str]:
    """Older pinned revisions ask for SPIRV-Headers as a CMake package; the Vulkan SDK has it."""
    bases = []
    if os.environ.get("VULKAN_SDK"):
        bases.append(Path(os.environ["VULKAN_SDK"]))
    for root in sorted(Path("/run/media").glob("*/*/VulkanSDK")):
        bases += sorted(root.iterdir(), reverse=True)
    for base in bases:
        headers = base / "Lib" / "cmake" / "SPIRV-Headers"
        include = base / "Include"
        if headers.is_dir() and include.is_dir():
            return [
                f"-DSPIRV-Headers_DIR={headers}",
                f"-DCMAKE_PREFIX_PATH={base}",
                f"-DCMAKE_C_FLAGS=-I{include}",
                f"-DCMAKE_CXX_FLAGS=-I{include}",
            ]
    return []


def vulkan_backend(package: Path, cache: Path) -> tuple[Path, Path]:
    source = cache / "backend" / "llama.cpp"
    if source.is_dir():
        head = subprocess.run(["git", "-C", str(source), "rev-parse", "HEAD"], capture_output=True, text=True).stdout.strip()
        if head != PINNED_LLAMACPP:
            source = cache / "backend-vulkan-source" / "llama.cpp"
    if not source.is_dir():
        source.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "clone", "--no-checkout", "https://github.com/ggml-org/llama.cpp.git", str(source)], check=True)
        subprocess.run(["git", "-C", str(source), "checkout", "--detach", PINNED_LLAMACPP], check=True)
    build = cache / "backend-vulkan"
    binary = build / "bin" / "llama-server"
    receipt = cache / "backend-vulkan-receipt.json"
    if not binary.is_file() or not receipt.is_file():
        print(f"building pinned llama.cpp {PINNED_LLAMACPP[:9]} with Vulkan in {build}")
        subprocess.run([
            "cmake", "-S", str(source), "-B", str(build), "-DCMAKE_BUILD_TYPE=Release",
            "-DGGML_VULKAN=ON", "-DLLAMA_CURL=OFF", "-DLLAMA_BUILD_TESTS=OFF", "-DLLAMA_BUILD_EXAMPLES=ON",
            *vulkan_cmake_args(),
        ], check=True)
        subprocess.run(["cmake", "--build", str(build), "--target", "llama-server", "-j", str(os.cpu_count() or 4)], check=True)
        sys.path.insert(0, str(package))
        from provenance import inspect_backend

        data = inspect_backend(binary)
        data.update(
            source_revision=PINNED_LLAMACPP,
            tracked_source_clean=True,
            mode="vulkan",
            source_directory=str(source),
        )
        receipt.write_text(json.dumps(data, indent=2) + "\n")
    return binary, receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="h2o-lightning decision + box API (shim)")
    parser.add_argument("--backend", choices=["cpu", "vulkan", "cuda"], default="cpu")
    parser.add_argument("--variant", choices=VARIANTS, default="Q8_0")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--backend-port", type=int, default=DEFAULT_BACKEND_PORT)
    parser.add_argument("--context", type=int, default=40960)
    parser.add_argument("--gpu-layers", type=int, default=99, help="vulkan/cuda offload; 0 keeps it on CPU")
    parser.add_argument("--gpu", default="0", help="CUDA_VISIBLE_DEVICES for --backend cuda")
    parser.add_argument("--no-images", dest="images", action="store_false", help="text decisions only")
    parser.add_argument("--restart", action="store_true", help="take the ports from whatever holds them")
    parser.add_argument("--status", action="store_true")
    parser.add_argument("--stop", action="store_true")
    args = parser.parse_args()

    if args.status:
        up = health(args.port)
        print(f"h2o-lightning shim :{args.port} — {'UP' if up else 'DOWN'}")
        return 0 if up else 1
    if args.stop:
        stop(args.port, args.backend_port)
        return 0
    if health(args.port):
        print(f"⚠️  :{args.port} already answers; pass --restart to take it over")
        return 0
    if args.restart:
        stop(args.port, args.backend_port)
        import time

        time.sleep(2)

    python = ensure_python()
    proof = prepare(python, args)
    env = dict(os.environ, LIGHTNING_BOX_ENABLED="1", PYTHONUNBUFFERED="1")
    os.makedirs(Path.home() / ".cache" / "h2o-lightning", exist_ok=True)
    os.chdir(Path.home() / ".cache" / "h2o-lightning")
    if args.backend == "vulkan":
        binary, receipt = vulkan_backend(Path(proof["package"]), args.cache)
        command = [
            str(python), str(Path(proof["package"]) / "serve.py"),
            "--model", proof["model"], "--llama-server", str(binary),
            "--backend-receipt", str(receipt), "--context", str(args.context),
            "--gpu-layers", str(args.gpu_layers),
            "--port", str(args.port), "--backend-port", str(args.backend_port),
        ]
    else:
        command = [
            str(python), str(ensure_bootstrap()),
            "--backend", args.backend, "--variant", args.variant,
            "--cache", str(args.cache), "--port", str(args.port), "--backend-port", str(args.backend_port),
        ]
        if args.backend == "cuda":
            command += ["--gpu", args.gpu]
        if args.images:
            command.append("--images")
    if args.backend == "vulkan" and args.images and proof.get("projector"):
        command += ["--mmproj", str(proof["projector"])]
    print(f"starting h2o-lightning ({args.variant}, {args.backend}) on http://127.0.0.1:{args.port}")
    print(f"box questions enabled; backend on :{args.backend_port}")
    os.execve(str(python), command, env)


if __name__ == "__main__":
    sys.exit(main())
