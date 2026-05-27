#!/usr/bin/env python3
"""Drop findings whose path:line is not an added (+) line in the PR diff.

Usage: filter_findings.py <findings.json> <pr.diff>
Writes surviving findings JSON to stdout. Logs `dropped N` to stderr.
Exit 0 on success regardless of how many findings survive.
"""
import json
import re
import sys
from collections import defaultdict


def parse_added_lines(diff_text):
    """Return {path: set(line_numbers)} of every '+' line on the new side."""
    added = defaultdict(set)
    current_path = None
    new_line = None
    for raw in diff_text.splitlines():
        m_path = re.match(r"^\+\+\+ b/(.+)$", raw)
        if m_path:
            current_path = m_path.group(1)
            new_line = None
            continue
        m_hunk = re.match(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@", raw)
        if m_hunk:
            new_line = int(m_hunk.group(1))
            continue
        if current_path is None or new_line is None:
            continue
        if raw.startswith("+++") or raw.startswith("---"):
            continue
        if raw.startswith("+"):
            added[current_path].add(new_line)
            new_line += 1
        elif raw.startswith("-"):
            pass  # no new-side advance
        elif raw.startswith(" ") or raw == "":
            new_line += 1
        # other markers (\ No newline at end of file, diff headers) — ignore

    return added


def keep(finding, added):
    path = finding.get("path")
    line = finding.get("line")
    end_line = finding.get("end_line")
    if not isinstance(path, str) or not isinstance(line, int):
        return False
    if path not in added:
        return False
    if line not in added[path]:
        return False
    if end_line is not None:
        if not isinstance(end_line, int) or end_line < line:
            return False
        for ln in range(line, end_line + 1):
            if ln not in added[path]:
                return False
    return True


def main():
    if len(sys.argv) != 3:
        print("usage: filter_findings.py <findings.json> <pr.diff>", file=sys.stderr)
        sys.exit(64)
    findings = json.load(open(sys.argv[1], encoding="utf-8"))
    diff_text = open(sys.argv[2], encoding="utf-8", errors="replace").read()
    added = parse_added_lines(diff_text)
    survivors = [f for f in findings if keep(f, added)]
    dropped = len(findings) - len(survivors)
    print(f"dropped {dropped}", file=sys.stderr)
    json.dump(survivors, sys.stdout)


if __name__ == "__main__":
    main()
