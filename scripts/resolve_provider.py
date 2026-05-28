#!/usr/bin/env python3
"""Resolve a model string to the API-key env var its provider needs.

Usage: resolve_provider.py <model-string>
Stdout: the env var name carrying the key (OPENAI_API_KEY | DEEPSEEK_API_KEY).
Exit codes:
  0 — always. Unrecognized models fall back to DeepSeek, matching prior
      behavior where any non-routed model used the DeepSeek key.
"""
import re
import sys

# Models that route to OpenAI. Matched case-insensitively against the model
# name (the part after any leading "<provider>/"). The reasoning-model class is
# [134] not [1-4] because OpenAI never released an "o2" family.
_OPENAI_NAME = re.compile(r"^(gpt-|chatgpt-|o[134])", re.IGNORECASE)


def resolve(model: str) -> str:
    model = model.strip()
    if model.lower().startswith("openai/"):
        return "OPENAI_API_KEY"
    # Strip a leading provider prefix (e.g. "deepseek/") before name match.
    # split returns the whole string unchanged when there is no "/".
    name = model.split("/", 1)[-1]
    if _OPENAI_NAME.match(name):
        return "OPENAI_API_KEY"
    return "DEEPSEEK_API_KEY"


def main():
    if len(sys.argv) != 2:
        print("usage: resolve_provider.py <model-string>", file=sys.stderr)
        sys.exit(64)
    print(resolve(sys.argv[1]))


if __name__ == "__main__":
    main()
