#!/usr/bin/env python3
"""Extract the last fenced ```json``` block from aider's stdout.

Usage: extract_json.py <aider-stdout-file>
Exit codes:
  0 — JSON array written to stdout
  2 — no fenced json block found
  3 — block found but JSON parse failed
"""
import json
import re
import sys


def main():
    if len(sys.argv) != 2:
        print("usage: extract_json.py <file>", file=sys.stderr)
        sys.exit(64)
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    blocks = re.findall(r"```json\s*\n(.*?)```", text, re.DOTALL)
    if not blocks:
        sys.exit(2)
    try:
        parsed = json.loads(blocks[-1])
    except json.JSONDecodeError as e:
        print(f"json parse error: {e}", file=sys.stderr)
        sys.exit(3)
    json.dump(parsed, sys.stdout)


if __name__ == "__main__":
    main()
