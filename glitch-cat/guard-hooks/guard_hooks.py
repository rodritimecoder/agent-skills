#!/usr/bin/env python3
import os
import sys
from pathlib import Path

bin_path = Path(__file__).resolve().parent / "bin" / "guard-hooks"
if bin_path.is_file() and os.access(bin_path, os.X_OK):
    os.execv(str(bin_path), [str(bin_path)] + sys.argv[1:])

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
import guard

if __name__ == "__main__":
    guard.main()
