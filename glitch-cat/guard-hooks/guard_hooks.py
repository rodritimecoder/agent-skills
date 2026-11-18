#!/usr/bin/env python3
import json
import os
import sys
from pathlib import Path

# The Rust binary is exec'd below, so a `wrap --dry-run` must be intercepted
# here at the Python wrapper before any native code can mutate anything.
_argv = sys.argv[1:]
if "wrap" in _argv and "--dry-run" in _argv:
    _plan = {"command": "wrap", "dry_run": True, "argv": _argv}
    print(json.dumps(_plan, indent=2) if "--json" in _argv else
          f"[dry-run] guard-hooks wrap: would apply guard with {_argv}")
    sys.exit(0)

bin_path = Path(__file__).resolve().parent / "bin" / "guard-hooks"
if bin_path.is_file() and os.access(bin_path, os.X_OK):
    os.execv(str(bin_path), [str(bin_path)] + sys.argv[1:])

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
import guard

if __name__ == "__main__":
    guard.main()
