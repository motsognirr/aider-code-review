#!/usr/bin/env python3
"""Extract the `## Summary` section body from aider's stdout.

Usage: extract_summary.py <aider-stdout-file>
Exit codes:
  0 — summary written to stdout
  2 — no usable summary: no `## Summary` heading in the response, or its body
      is empty once aider's usage report is removed (the caller falls back
      to a generated summary either way)
"""
import re
import sys

from aider_output import answer_text

# aider's usage report, printed after the response: `Tokens: ... received.`
# then `Cost: ...`, on the same line or the next (aider/coders/base_coder.py).
# Anchored to the end so a summary that merely mentions tokens is untouched.
USAGE_REPORT = re.compile(
    r"\n+Tokens: [^\n]* received\.(?:[ \n]Cost: [^\n]*)?\s*\Z"
)


def main():
    if len(sys.argv) != 2:
        print("usage: extract_summary.py <file>", file=sys.stderr)
        sys.exit(64)
    text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
    answer = answer_text(text)
    # The last heading, like extract_json's last block: earlier ones are drafts.
    matches = list(re.finditer(
        r"^##\s+Summary\s*\n(.*?)(?=^##\s|\Z)",
        answer,
        re.DOTALL | re.MULTILINE,
    ))
    if not matches:
        sys.exit(2)
    body = USAGE_REPORT.sub("", "\n" + matches[-1].group(1)).strip()
    if not body:
        sys.exit(2)  # nothing but the usage report: no summary to post
    sys.stdout.write(body + "\n")


if __name__ == "__main__":
    main()
