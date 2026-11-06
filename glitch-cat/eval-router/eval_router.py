#!/usr/bin/env python3
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent
sys.path.append(str(SKILL_DIR / "scripts"))
import router

if __name__ == "__main__":
    router.main()
