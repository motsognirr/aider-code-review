#!/usr/bin/env python3
"""Redact credential values from files, in place.

Usage: scrub_secrets.py <file>...
Replaces the value of each credential env var below with `[REDACTED]`. Run
over everything whose contents can reach the PR (aider's stdout and stderr).
"""
import os
import sys

SECRET_VARS = ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "GH_TOKEN", "GITHUB_TOKEN")


def main():
    if len(sys.argv) < 2:
        print("usage: scrub_secrets.py <file>...", file=sys.stderr)
        sys.exit(64)
    secrets = [v for v in (os.environ.get(k, "") for k in SECRET_VARS) if v]
    for path in sys.argv[1:]:
        if not os.path.exists(path):
            continue  # nothing was written, so nothing can leak
        text = open(path, encoding="utf-8", errors="replace").read()
        for val in secrets:
            text = text.replace(val, "[REDACTED]")
        open(path, "w", encoding="utf-8").write(text)


if __name__ == "__main__":
    main()
