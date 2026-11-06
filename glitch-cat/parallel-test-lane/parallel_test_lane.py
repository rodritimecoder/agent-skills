#!/usr/bin/env python3
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent / "scripts"))
import test_lane

if __name__ == "__main__":
    test_lane.main()
