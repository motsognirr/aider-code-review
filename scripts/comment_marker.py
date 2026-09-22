#!/usr/bin/env python3
"""Build this reviewer's HTML comment marker.

Every comment the action posts is stamped with a marker, and each run deletes
its own prior comments by matching it. The marker is therefore an identity: if
two jobs share one, each job's cleanup deletes the other's fresh comments.

Scoping the marker by model (or an explicit `comment_key`) gives concurrent
reviewers disjoint comment namespaces.
"""

import re
import sys

LEGACY_MARKER = "<!-- aider-code-review -->"
FALLBACK_KEY = "default"


def sanitize(key: str) -> str:
    """Make `key` safe to embed in an HTML comment.

    `--` terminates an HTML comment early, which would leak the marker into the
    rendered body as visible text, so it is collapsed along with any other
    character that has no business inside a marker.
    """
    key = key.strip()
    if not key:
        return FALLBACK_KEY
    key = re.sub(r"[^A-Za-z0-9._/-]", "-", key)
    key = re.sub(r"-{2,}", "-", key)
    return key or FALLBACK_KEY


def build(key: str) -> str:
    return f"<!-- aider-code-review:{sanitize(key)} -->"


if __name__ == "__main__":
    print(build(sys.argv[1] if len(sys.argv) > 1 else ""))
