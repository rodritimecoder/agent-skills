#!/usr/bin/env python3
"""Example plan: Discover audio transcription tool and query its spec."""
import json
from omnicli_tools import search, spec

def main():
    print("--- Searching for audio transcription tools ---")
    results = search("transcribe recorded audio", limit=3)
    for r in results:
        print(f"Skill: {r.get('skill')} (Score: {r.get('score', 0):.2f})")

    print("\n--- Inspecting Zoom specifications ---")
    zoom_specs = spec(grep="zoom", limit=2)
    for s in zoom_specs:
        print(f"Tool ID: {s.get('id')}")
        print(f"Summary: {s.get('summary')}")

if __name__ == "__main__":
    import sys
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)
    main()
