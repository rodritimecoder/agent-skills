#!/usr/bin/env python3
"""Example plan: Query tool catalog, filter in Python memory, and format summary.

This demonstrates Cloudflare's Code Mode: data filtering and transformation
happen entirely in Python memory, so intermediate bulky responses never
enter the model's prompt context.
"""
from omnicli_tools import spec

def main():
    # Retrieve specs for decision tools without loading full schemas into context
    tools = spec(grep="decide|jev")
    
    # Filter in memory using Python logic
    active_tools = [t for t in tools if not t.get("disabled", False)]
    
    # Print only the essential distilled output
    print(f"Found {len(active_tools)} active decision tools:")
    for t in active_tools[:5]:
        print(f"  - {t['id']}: {t.get('summary', '')[:80]}")

if __name__ == "__main__":
    import sys
    if "-h" in sys.argv or "--help" in sys.argv:
        print(__doc__)
        sys.exit(0)
    main()
