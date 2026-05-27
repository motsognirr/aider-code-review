#!/usr/bin/env python3
"""Extract the `## Summary` section body from aider's stdout.

Usage: extract_summary.py <aider-stdout-file>
Exit codes:
  0 — summary written to stdout
  2 — no `## Summary` heading found
"""
import re
import sys


def main():
    if len(sys.argv) != 2:
        print("usage: extract_summary.py <file>", file=sys.stderr)
        sys.exit(64)
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    match = re.search(
        r"^##\s+Summary\s*\n(.*?)(?=^##\s|\Z)",
        text,
        re.DOTALL | re.MULTILINE,
    )
    if not match:
        sys.exit(2)
    sys.stdout.write(match.group(1).strip() + "\n")


if __name__ == "__main__":
    main()
