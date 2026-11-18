#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent / "modules"))
from ocr_engine import OCREngine, LIGHTON_MODEL_DIR


def _reexec_in_venv() -> None:
    """Re-exec under the skill venv when PyMuPDF is missing.

    PDF OCR needs PyMuPDF, which is not installed in the system interpreter.
    The skill ships a `.venv` symlink for exactly this, so hop into it once
    (guarded by an env var) and then let the normal code path run.
    """
    try:
        import pymupdf  # noqa: F401
        return
    except ImportError:
        pass
    if os.environ.get("_OCR_VENV_REEXEC") == "1":
        return
    here = Path(__file__).resolve()
    # Bundle copies are rsynced with `--exclude .venv`, so the in-tree symlink is
    # absent there; fall back to the machine-wide location it normally points at.
    candidates = (
        here.parent / ".venv" / "bin" / "python",
        Path.home() / ".venvs" / here.parent.name / "bin" / "python",
    )
    venv_py = next((c for c in candidates if c.is_file()), None)
    if venv_py is None:
        return
    try:
        if venv_py.resolve() == Path(sys.executable).resolve():
            return
    except OSError:
        return
    env = dict(os.environ, _OCR_VENV_REEXEC="1")
    os.execve(str(venv_py), [str(venv_py), str(here), *sys.argv[1:]], env)


def main():
    _reexec_in_venv()

    parent_parser = argparse.ArgumentParser(add_help=False)
    parent_parser.add_argument("--json", action="store_true", help="Output machine-readable JSON format")
    parent_parser.add_argument("--host", default=None, help="OCR server host (default: $OCR_HOST or 127.0.0.1, supports Tailscale *.ts.net)")
    parent_parser.add_argument("--lighton-port", type=int, metavar="PORT", default=8082, help="LightOnOCR port (default: 8082)")

    parser = argparse.ArgumentParser(
        description="ocr — LightOnOCR-3-0.8B document, PDF and slide OCR on :8082",
        parents=[parent_parser]
    )
    sub = parser.add_subparsers(dest="command")

    # Primary OCR parser
    p_read = sub.add_parser("read", aliases=["doc", "scan"], parents=[parent_parser], help="Document, PDF and slide OCR via LightOnOCR")
    p_read.add_argument("file", help="Input document (.pdf) or image (.png/.jpg)")
    p_read.add_argument("--prompt", "-p", default=None, help="Custom extraction prompt (transcription when omitted)")
    p_read.add_argument("--pages", help="PDF page range selection (e.g. 1-3,5)")
    p_read.add_argument("--engine", choices=["lighton"], default="lighton",
                        help="Document engine; LightOnOCR is the only engine and the default")
    p_read.add_argument("--assets", metavar="DIR", default=None,
                        help="Write figure crops (PNG) into DIR and link them from the Markdown (grounding)")
    p_read.add_argument("--grounding", action="store_true",
                        help="Grounding prompt (default; kept for explicitness)")
    p_read.add_argument("--transcribe", action="store_true",
                        help="Force plain transcription instead of the grounding default")
    p_read.add_argument("--output", "-o", help="Write output to text/markdown file")

    # Doctor
    sub.add_parser("doctor", parents=[parent_parser], help="Check LightOnOCR hardware, models, and server port")

    # Server manager
    p_srv = sub.add_parser("server", parents=[parent_parser], help="Manage the local LightOnOCR server daemon")
    p_srv.add_argument("action", choices=["start", "stop", "status", "restart"], help="Lifecycle action")
    p_srv.add_argument("--engine", choices=["lighton"], default="lighton", help="Target engine (LightOnOCR only)")

    # Support running `ocr file.png` directly without subcommand
    if len(sys.argv) > 1 and not sys.argv[1].startswith("-") and sys.argv[1] not in ("read", "doc", "scan", "doctor", "server"):
        sys.argv.insert(1, "read")

    args = parser.parse_args()
    engine = OCREngine(lighton_port=args.lighton_port, host=args.host)

    if args.command in ("read", "doc", "scan", None):
        if not getattr(args, "file", None):
            parser.print_help()
            sys.exit(1)

        file_p = Path(args.file).resolve()
        if not file_p.is_file():
            sys.exit(f"❌ Error: File not found: {args.file}")

        if args.transcribe or args.prompt:
            res = engine.ocr_document(file_p, prompt=args.prompt, pages=args.pages)
        else:
            res = engine.ocr_document_lighton(
                file_p,
                pages=args.pages,
                grounding=True,
                assets_dir=Path(args.assets).expanduser() if args.assets else None,
            )

        if args.output:
            target = Path(args.output).resolve()
            payload = json.dumps(res, indent=2) if args.json else res["text"]
            if not args.json:
                for asset in res.get("assets") or []:
                    try:
                        payload = payload.replace(asset["path"], os.path.relpath(asset["path"], target.parent))
                    except (KeyError, ValueError):
                        pass
            target.write_text(payload, encoding="utf-8")
        if res.get("assets") and not args.json:
            print(f"🖼  {len(res['assets'])} figure(s) → {Path(args.assets).resolve()}", file=sys.stderr)

        if args.json:
            print(json.dumps(res, indent=2))
        else:
            print(res["text"])

    elif args.command == "doctor":
        online = engine.is_lighton_online()
        doc = {
            "engine": "LightOnOCR-3-0.8B",
            "port": args.lighton_port,
            "online": online,
            "models_ready": LIGHTON_MODEL_DIR.is_dir(),
        }
        if args.json:
            print(json.dumps(doc, indent=2))
        else:
            print("🔍 [ocr] Diagnostic Health Check:")
            print(f"  Engine           : {doc['engine']} (port {doc['port']})")
            print(f"  Status           : {'🟢 Active' if online else '⚪ Inactive (auto-start ready)'}")
            print(f"  Weights          : {'🟢 Present' if doc['models_ready'] else '🔴 Missing'}")

    elif args.command == "server":
        if args.action == "status":
            st = {"lighton": "online" if engine.is_lighton_online() else "offline"}
            if args.json:
                print(json.dumps(st, indent=2))
            else:
                print(f"LightOnOCR (:8082): {st['lighton'].upper()}")

        elif args.action in ("start", "restart"):
            if args.action == "restart":
                subprocess.run(["fuser", "-k", f"{args.lighton_port}/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(1.0)

            ok = engine.ensure_lighton()
            if args.json:
                print(json.dumps({"action": args.action, "target": "lighton", "results": {"lighton": "started" if ok else "failed"}}, indent=2))
            else:
                print(f"LightOnOCR (:8082): {'STARTED' if ok else 'FAILED'}")

        elif args.action == "stop":
            ports = [args.lighton_port]
            for p in ports:
                subprocess.run(["fuser", "-k", f"{p}/tcp"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if args.json:
                print(json.dumps({"action": "stop", "target": "lighton", "ports": ports, "status": "stopped"}, indent=2))
            else:
                print(f"Stopped server daemons on ports: {ports}")


if __name__ == "__main__":
    main()
