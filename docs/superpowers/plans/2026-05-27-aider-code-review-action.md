# aider-code-review Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build `motsognirr/aider-code-review@v1`, a reusable, fork-safe composite GitHub Action that runs aider with DeepSeek to perform agentic PR review.

**Architecture:** Composite action whose entrypoint is a bash orchestrator. Pure-logic units (JSON extraction, summary extraction, hallucination-guard diff parsing) are Python scripts (stdlib only) — testable with pytest. Network-touching units (`gh api` calls for fetching diff/files, posting comments) are bash. aider is installed at runtime via `pip install --user`. Targets self-hosted macOS runners.

**Tech Stack:** Bash, Python 3 (stdlib), pytest, GitHub CLI (`gh`), `jq`, aider-chat, DeepSeek API.

**Spec:** `docs/superpowers/specs/2026-05-27-aider-code-review-action-design.md`

**Deviation from spec:** Tests use pytest, not bats-core; pure-logic units are Python, not bash. Rationale: unified-diff hunk parsing is significantly cleaner in Python than bash, and pytest is the natural test framework for Python. Functional behavior is unchanged.

---

## File Structure

| Path | Responsibility |
|---|---|
| `action.yml` | Composite action manifest — inputs, runs, wires steps together |
| `scripts/run_review.sh` | Bash orchestrator — top-level entry called by `action.yml` |
| `scripts/fetch_pr_context.sh` | `gh api` wrapper — fetches diff, metadata, base/head file blobs into sandbox |
| `scripts/post_comments.sh` | `gh api` wrapper — deletes prior bot comments, posts inline + summary |
| `scripts/extract_json.py` | Pure: extracts last fenced ```json``` block from aider stdout |
| `scripts/extract_summary.py` | Pure: extracts `## Summary` section from aider stdout |
| `scripts/filter_findings.py` | Pure: drops findings whose `path:line` isn't a `+` line in the PR diff |
| `prompts/architect.md` | aider's review prompt (structured-output instructions) |
| `tests/test_extract_json.py` | pytest cases for JSON extraction |
| `tests/test_extract_summary.py` | pytest cases for summary extraction |
| `tests/test_filter_findings.py` | pytest cases for the hallucination guard |
| `tests/fixtures/*.diff` | Sample unified diffs |
| `tests/fixtures/*.json` | Sample findings JSON |
| `tests/fixtures/*.txt` | Sample aider stdout blobs |
| `README.md` | Usage, inputs, fork-safety model |
| `.gitignore` | Standard Python + macOS ignores |
| `.github/workflows/ci.yml` | Runs pytest on push |
| `.github/workflows/self-test.yml` | Runs the action on its own PRs with `dry_run: true` |
| `.github/workflows/release.yml` | Updates moving `v1` tag when a `v1.x.y` tag is pushed |

---

## Task 1: Repo bootstrap

**Files:**
- Create: `.gitignore`
- Create: `README.md` (skeleton; full content in Task 14)

- [ ] **Step 1: Write `.gitignore`**

```
# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/

# Test artefacts
.pytest_cache/
.coverage
htmlcov/

# macOS
.DS_Store

# Editor
.vscode/
.idea/

# Runtime
*.log
/tmp-sandbox/
```

- [ ] **Step 2: Write skeleton `README.md`**

```markdown
# aider-code-review

Reusable GitHub Action: agentic PR review powered by [aider](https://aider.chat) with DeepSeek as the backend model.

Full documentation lands with v1.0.0.
```

- [ ] **Step 3: Commit**

```bash
git add .gitignore README.md
git commit -m "chore: add .gitignore and README skeleton"
```

---

## Task 2: Test harness smoke test

**Files:**
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `tests/test_smoke.py`

Goal: prove pytest runs from the repo root before writing any production code.

- [ ] **Step 1: Create `tests/__init__.py`** (empty file)

```bash
touch tests/__init__.py
```

- [ ] **Step 2: Create `tests/conftest.py`**

```python
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "scripts"))
```

- [ ] **Step 3: Write the failing smoke test**

`tests/test_smoke.py`:

```python
def test_pytest_runs():
    assert 1 + 1 == 2
```

- [ ] **Step 4: Run pytest**

Run: `python3 -m pytest tests/test_smoke.py -v`
Expected: 1 passed.

If pytest is missing: `pip install --user pytest` and re-run.

- [ ] **Step 5: Commit**

```bash
git add tests/
git commit -m "test: add pytest harness with smoke test"
```

---

## Task 3: `extract_json.py` — extract fenced JSON block

**Files:**
- Create: `tests/fixtures/aider_stdout_one_block.txt`
- Create: `tests/fixtures/aider_stdout_multi_block.txt`
- Create: `tests/fixtures/aider_stdout_no_block.txt`
- Create: `tests/fixtures/aider_stdout_malformed.txt`
- Create: `tests/test_extract_json.py`
- Create: `scripts/extract_json.py`

Spec contract: read aider stdout from a file path arg, write the parsed JSON array to stdout, exit 0 on success, exit 2 on no block, exit 3 on parse failure.

- [ ] **Step 1: Write fixture — one fenced block**

`tests/fixtures/aider_stdout_one_block.txt`:

````
Reviewing the diff now.

```json
[
  {"path": "src/foo.py", "line": 10, "severity": "high", "category": "bug", "body": "Off-by-one."}
]
```

## Summary
Looks fine overall.
````

- [ ] **Step 2: Write fixture — multiple fenced blocks (last wins)**

`tests/fixtures/aider_stdout_multi_block.txt`:

````
Draft:

```json
[{"path": "old.py", "line": 1, "severity": "low", "category": "maintainability", "body": "draft"}]
```

Revised:

```json
[{"path": "src/bar.py", "line": 5, "severity": "high", "category": "security", "body": "SQL injection."}]
```
````

- [ ] **Step 3: Write fixture — no fenced block**

`tests/fixtures/aider_stdout_no_block.txt`:

```
Sorry, I could not produce structured output.
```

- [ ] **Step 4: Write fixture — malformed JSON**

`tests/fixtures/aider_stdout_malformed.txt`:

````
```json
[{"path": "src/x.py", "line": 1, this is not valid json
```
````

- [ ] **Step 5: Write the failing tests**

`tests/test_extract_json.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_json.py"
FIX = Path(__file__).resolve().parent / "fixtures"


def run(fixture_name):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(FIX / fixture_name)],
        capture_output=True,
        text=True,
    )


def test_one_block_emits_array():
    result = run("aider_stdout_one_block.txt")
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert len(parsed) == 1
    assert parsed[0]["path"] == "src/foo.py"


def test_multi_block_uses_last():
    result = run("aider_stdout_multi_block.txt")
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed[0]["path"] == "src/bar.py"


def test_no_block_exits_2():
    result = run("aider_stdout_no_block.txt")
    assert result.returncode == 2
    assert result.stdout.strip() == ""


def test_malformed_exits_3():
    result = run("aider_stdout_malformed.txt")
    assert result.returncode == 3
```

- [ ] **Step 6: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_extract_json.py -v`
Expected: 4 failures (script doesn't exist).

- [ ] **Step 7: Write `scripts/extract_json.py`**

```python
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
```

- [ ] **Step 8: Make script executable**

```bash
chmod +x scripts/extract_json.py
```

- [ ] **Step 9: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_extract_json.py -v`
Expected: 4 passed.

- [ ] **Step 10: Commit**

```bash
git add scripts/extract_json.py tests/test_extract_json.py tests/fixtures/aider_stdout_*.txt
git commit -m "feat: add extract_json.py with pytest coverage"
```

---

## Task 4: `extract_summary.py` — extract `## Summary` section

**Files:**
- Create: `tests/fixtures/aider_stdout_with_summary.txt`
- Create: `tests/fixtures/aider_stdout_no_summary.txt`
- Create: `tests/fixtures/aider_stdout_summary_then_section.txt`
- Create: `tests/test_extract_summary.py`
- Create: `scripts/extract_summary.py`

Spec contract: read aider stdout from a file path arg, write the `## Summary` body to stdout (everything from after the `## Summary` heading until the next `##` heading or EOF). Exit 0 if found, exit 2 if absent.

- [ ] **Step 1: Write fixture — with summary**

`tests/fixtures/aider_stdout_with_summary.txt`:

````
```json
[]
```

## Summary

Two medium-severity findings, one perf issue in the hot path.
Nothing blocking.
````

- [ ] **Step 2: Write fixture — no summary**

`tests/fixtures/aider_stdout_no_summary.txt`:

````
```json
[]
```

Done.
````

- [ ] **Step 3: Write fixture — summary followed by another section**

`tests/fixtures/aider_stdout_summary_then_section.txt`:

````
## Summary

All good.

## Notes

Some notes the model added.
````

- [ ] **Step 4: Write the failing tests**

`tests/test_extract_summary.py`:

```python
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_summary.py"
FIX = Path(__file__).resolve().parent / "fixtures"


def run(fixture_name):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(FIX / fixture_name)],
        capture_output=True,
        text=True,
    )


def test_extracts_summary_body():
    result = run("aider_stdout_with_summary.txt")
    assert result.returncode == 0
    assert "Two medium-severity findings" in result.stdout
    assert "Nothing blocking." in result.stdout


def test_missing_summary_exits_2():
    result = run("aider_stdout_no_summary.txt")
    assert result.returncode == 2


def test_summary_stops_at_next_section():
    result = run("aider_stdout_summary_then_section.txt")
    assert result.returncode == 0
    assert "All good." in result.stdout
    assert "Some notes" not in result.stdout
    assert "## Notes" not in result.stdout
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_extract_summary.py -v`
Expected: 3 failures.

- [ ] **Step 6: Write `scripts/extract_summary.py`**

```python
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
```

- [ ] **Step 7: Make executable**

```bash
chmod +x scripts/extract_summary.py
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_extract_summary.py -v`
Expected: 3 passed.

- [ ] **Step 9: Commit**

```bash
git add scripts/extract_summary.py tests/test_extract_summary.py tests/fixtures/aider_stdout_*.txt
git commit -m "feat: add extract_summary.py with pytest coverage"
```

---

## Task 5: `filter_findings.py` — hallucination guard, fixtures

**Files:**
- Create: `tests/fixtures/diff_basic.diff`
- Create: `tests/fixtures/diff_multifile.diff`
- Create: `tests/fixtures/diff_with_deletions.diff`

This task only creates fixtures so they're ready for the test cases in Task 6. Each fixture is a real unified diff.

- [ ] **Step 1: Write `tests/fixtures/diff_basic.diff`**

A single file with one hunk adding two lines and modifying one in context:

```
diff --git a/src/foo.py b/src/foo.py
index 0000001..0000002 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -10,5 +10,7 @@ def f():
     a = 1
     b = 2
-    c = a + b
+    c = a - b
+    d = c * 2
+    e = d + 1
     return c
```

(After this hunk: line 10 = `    a = 1` context, line 11 = `    b = 2` context, line 12 = `    c = a - b` `+`, line 13 = `    d = c * 2` `+`, line 14 = `    e = d + 1` `+`, line 15 = `    return c` context.)

- [ ] **Step 2: Write `tests/fixtures/diff_multifile.diff`**

Two files, distinct hunks:

```
diff --git a/src/foo.py b/src/foo.py
index 0000001..0000002 100644
--- a/src/foo.py
+++ b/src/foo.py
@@ -1,3 +1,4 @@
 import os
+import sys
 
 def f():
diff --git a/src/bar.py b/src/bar.py
index 0000003..0000004 100644
--- a/src/bar.py
+++ b/src/bar.py
@@ -20,2 +20,3 @@ def g():
     pass
+    return None
 
```

- [ ] **Step 3: Write `tests/fixtures/diff_with_deletions.diff`**

A hunk that only deletes lines (no `+` lines):

```
diff --git a/src/old.py b/src/old.py
index 0000005..0000006 100644
--- a/src/old.py
+++ b/src/old.py
@@ -5,4 +5,2 @@ def h():
     keep1
-    drop1
-    drop2
     keep2
```

(After this hunk: line 5 = `    keep1` context, line 6 = `    keep2` context. No `+` lines.)

- [ ] **Step 4: Commit**

```bash
git add tests/fixtures/diff_*.diff
git commit -m "test: add unified diff fixtures for filter_findings"
```

---

## Task 6: `filter_findings.py` — hallucination guard, tests & implementation

**Files:**
- Create: `tests/test_filter_findings.py`
- Create: `scripts/filter_findings.py`

Spec contract: read findings JSON from a file path arg, read PR diff from a second file path arg, write filtered findings JSON to stdout. Drop any finding whose `path` is not in the diff, whose `line` is not on the new (right) side of any hunk in that file as a `+` (added) line, or whose `end_line` (if present) is < `line` or not also a `+` line. Print dropped count to stderr.

- [ ] **Step 1: Write the failing tests**

`tests/test_filter_findings.py`:

```python
import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "filter_findings.py"
FIX = Path(__file__).resolve().parent / "fixtures"


def run(findings, diff_fixture, tmp_path):
    findings_path = tmp_path / "findings.json"
    findings_path.write_text(json.dumps(findings))
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(findings_path), str(FIX / diff_fixture)],
        capture_output=True,
        text=True,
    )


def test_keeps_added_line(tmp_path):
    findings = [{"path": "src/foo.py", "line": 12, "severity": "high",
                 "category": "bug", "body": "issue on the new c assignment"}]
    result = run(findings, "diff_basic.diff", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == findings


def test_drops_context_line(tmp_path):
    findings = [{"path": "src/foo.py", "line": 10, "severity": "low",
                 "category": "maintainability", "body": "comment on context line"}]
    result = run(findings, "diff_basic.diff", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_drops_unknown_file(tmp_path):
    findings = [{"path": "src/other.py", "line": 1, "severity": "high",
                 "category": "bug", "body": "x"}]
    result = run(findings, "diff_basic.diff", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_drops_line_outside_hunks(tmp_path):
    findings = [{"path": "src/foo.py", "line": 999, "severity": "high",
                 "category": "bug", "body": "out of range"}]
    result = run(findings, "diff_basic.diff", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_drops_end_line_less_than_line(tmp_path):
    findings = [{"path": "src/foo.py", "line": 14, "end_line": 13,
                 "severity": "high", "category": "bug", "body": "bad range"}]
    result = run(findings, "diff_basic.diff", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_keeps_valid_multiline_range(tmp_path):
    findings = [{"path": "src/foo.py", "line": 12, "end_line": 14,
                 "severity": "medium", "category": "perf",
                 "body": "all three new lines"}]
    result = run(findings, "diff_basic.diff", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == findings


def test_drops_end_line_with_non_added_in_range(tmp_path):
    # line 11 is context (not '+'), so a 11..14 range fails the guard
    findings = [{"path": "src/foo.py", "line": 11, "end_line": 14,
                 "severity": "medium", "category": "perf", "body": "x"}]
    result = run(findings, "diff_basic.diff", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_multifile_keeps_each_file_findings(tmp_path):
    findings = [
        {"path": "src/foo.py", "line": 2, "severity": "low",
         "category": "maintainability", "body": "import sys"},
        {"path": "src/bar.py", "line": 21, "severity": "low",
         "category": "maintainability", "body": "return None"},
    ]
    result = run(findings, "diff_multifile.diff", tmp_path)
    assert result.returncode == 0
    out = json.loads(result.stdout)
    assert len(out) == 2


def test_deletion_only_hunk_drops_everything(tmp_path):
    findings = [{"path": "src/old.py", "line": 5, "severity": "high",
                 "category": "bug", "body": "context"}]
    result = run(findings, "diff_with_deletions.diff", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == []


def test_reports_drop_count_on_stderr(tmp_path):
    findings = [
        {"path": "src/foo.py", "line": 12, "severity": "high",
         "category": "bug", "body": "keep"},
        {"path": "src/foo.py", "line": 999, "severity": "high",
         "category": "bug", "body": "drop"},
    ]
    result = run(findings, "diff_basic.diff", tmp_path)
    assert result.returncode == 0
    assert "dropped 1" in result.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_filter_findings.py -v`
Expected: 10 failures.

- [ ] **Step 3: Write `scripts/filter_findings.py`**

```python
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
```

- [ ] **Step 4: Make executable**

```bash
chmod +x scripts/filter_findings.py
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_filter_findings.py -v`
Expected: 10 passed.

- [ ] **Step 6: Commit**

```bash
git add scripts/filter_findings.py tests/test_filter_findings.py
git commit -m "feat: add filter_findings.py hallucination guard"
```

---

## Task 7: `prompts/architect.md` — review prompt

**Files:**
- Create: `prompts/architect.md`

No tests for prose, but the content directly drives output quality so it gets its own task.

- [ ] **Step 1: Write `prompts/architect.md`**

````markdown
# Pull request review

You are reviewing a pull request. Your output drives an automated reviewer
that posts inline comments to GitHub, so you must produce structured output.

## What to look for

- **Bugs**: logic errors, off-by-ones, null/undefined handling, incorrect
  control flow, race conditions, broken invariants.
- **Security**: injection, auth/authz mistakes, leaked secrets, unsafe
  deserialization, SSRF, path traversal, weak crypto.
- **Performance**: O(n²) over likely-hot data, unnecessary I/O, blocking
  calls on async paths.
- **Maintainability**: contracts violated, dead code, unsafe API changes
  that will break callers.

Do **not** comment on:
- Style, formatting, naming preferences, import order, trailing whitespace.
- Documentation that is merely absent (only call out wrong docs).
- Suggestions to add tests unless a code path is genuinely untested AND risky.
- Speculative refactors.

## Constraints

- Limit yourself to 3–10 findings. Prefer fewer high-signal findings over
  many low-signal ones. If the diff is clean, return an empty array.
- Every finding MUST reference a `path` and `line` where `line` is the line
  number in the NEW (head) version of the file, and that line MUST be a line
  the PR adds (a `+` line in the diff). Pure context lines are not valid
  targets. Lines that the PR only deletes are not valid targets.
- If you want to comment on a multi-line range, set `end_line` ≥ `line` AND
  ensure EVERY line in `[line, end_line]` is a `+` line in the diff.

## Output format

Emit a single fenced ```json``` block containing a JSON array (possibly
empty) of findings. Schema per finding:

```
{
  "path": "src/foo.py",
  "line": 42,
  "end_line": 47,            // optional; omit for single-line findings
  "severity": "high" | "medium" | "low",
  "category": "bug" | "security" | "perf" | "maintainability",
  "body": "Markdown comment text. Be concrete. Reference the exact symbol or expression."
}
```

After the JSON block, write a `## Summary` section (a short freeform
paragraph) that will be posted as the top-level PR comment. Mention the
overall risk level and the headline finding (if any).

Do not emit anything else outside the JSON block and the `## Summary`
section — no preamble, no explanatory text between them.
````

- [ ] **Step 2: Commit**

```bash
git add prompts/architect.md
git commit -m "feat: add architect review prompt"
```

---

## Task 8: `fetch_pr_context.sh` — gh wrapper for diff + file blobs

**Files:**
- Create: `scripts/fetch_pr_context.sh`

This script wraps network calls; we don't unit-test it (would require mocking `gh`). It is exercised end-to-end by `self-test.yml` (Task 16).

Contract: takes env vars `REPO`, `PR_NUMBER`, `SANDBOX`, `MAX_FILES`, `EXCLUDE_PATTERNS`. Populates `$SANDBOX/pr.diff`, `$SANDBOX/meta.json`, `$SANDBOX/head/<path>` per included changed file. Writes a newline-separated list of included paths to `$SANDBOX/included_files.txt`. Exits non-zero on any `gh` failure.

- [ ] **Step 1: Write `scripts/fetch_pr_context.sh`**

```bash
#!/usr/bin/env bash
# Fetch PR context (diff, metadata, head file blobs) into $SANDBOX.
# Required env: REPO, PR_NUMBER, SANDBOX, MAX_FILES, EXCLUDE_PATTERNS
set -euo pipefail

: "${REPO:?REPO is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${SANDBOX:?SANDBOX is required}"
: "${MAX_FILES:=20}"
: "${EXCLUDE_PATTERNS:=}"

mkdir -p "$SANDBOX/head"

echo "Fetching PR diff..."
gh pr diff "$PR_NUMBER" --repo "$REPO" --patch > "$SANDBOX/pr.diff"

echo "Fetching PR metadata..."
gh api "repos/$REPO/pulls/$PR_NUMBER" > "$SANDBOX/meta.json"

HEAD_SHA=$(jq -r '.head.sha' < "$SANDBOX/meta.json")
echo "$HEAD_SHA" > "$SANDBOX/head_sha"
jq -r '.base.sha' < "$SANDBOX/meta.json" > "$SANDBOX/base_sha"
jq -r '.author_association' < "$SANDBOX/meta.json" > "$SANDBOX/author_association"

echo "Listing changed files..."
gh api --paginate "repos/$REPO/pulls/$PR_NUMBER/files" \
  | jq -r '.[] | select(.status != "removed") | .filename' \
  > "$SANDBOX/all_changed_files.txt"

# Apply exclude patterns + max_files cap.
> "$SANDBOX/included_files.txt"
included=0
total=0
while IFS= read -r path; do
  total=$((total + 1))
  if [ -n "$EXCLUDE_PATTERNS" ]; then
    excluded=0
    while IFS= read -r pat; do
      [ -z "$pat" ] && continue
      # shellcheck disable=SC2053
      case "$path" in
        $pat) excluded=1; break ;;
      esac
    done <<< "$EXCLUDE_PATTERNS"
    [ "$excluded" -eq 1 ] && continue
  fi
  if [ "$included" -ge "$MAX_FILES" ]; then
    continue
  fi
  printf '%s\n' "$path" >> "$SANDBOX/included_files.txt"
  included=$((included + 1))
done < "$SANDBOX/all_changed_files.txt"

echo "Included $included of $total changed files (max_files=$MAX_FILES)."
echo "$total" > "$SANDBOX/total_changed_files"
echo "$included" > "$SANDBOX/included_files_count"

echo "Fetching head blobs..."
while IFS= read -r path; do
  dest="$SANDBOX/head/$path"
  mkdir -p "$(dirname "$dest")"
  # Tolerate 404 (deleted files were already filtered above, but a race is possible).
  if ! gh api "repos/$REPO/contents/$path?ref=$HEAD_SHA" \
       --jq '.content' 2>/dev/null \
       | base64 --decode > "$dest" 2>/dev/null; then
    echo "warn: failed to fetch head blob for $path; skipping" >&2
    rm -f "$dest"
  fi
done < "$SANDBOX/included_files.txt"

echo "Fetch complete."
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/fetch_pr_context.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/fetch_pr_context.sh
git commit -m "feat: add fetch_pr_context.sh gh wrapper"
```

---

## Task 9: `post_comments.sh` — gh wrapper for posting

**Files:**
- Create: `scripts/post_comments.sh`

Contract: takes env vars `REPO`, `PR_NUMBER`, `SANDBOX`, `DRY_RUN`. Reads `$SANDBOX/findings.json` (filtered), `$SANDBOX/summary.md`, `$SANDBOX/head_sha`. Deletes any prior bot comments carrying the `<!-- aider-code-review -->` marker, then posts one inline comment per finding and one summary issue comment. Writes the summary comment URL to `$SANDBOX/summary_url`. Writes counts to `$SANDBOX/posted_inline_count` and `$SANDBOX/failed_posts_count`.

- [ ] **Step 1: Write `scripts/post_comments.sh`**

```bash
#!/usr/bin/env bash
# Delete prior bot comments and post fresh inline + summary comments.
# Required env: REPO, PR_NUMBER, SANDBOX
# Optional env: DRY_RUN (true|false, default false)
set -euo pipefail

: "${REPO:?REPO is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${SANDBOX:?SANDBOX is required}"
: "${DRY_RUN:=false}"

MARKER="<!-- aider-code-review -->"

FINDINGS_FILE="$SANDBOX/findings.json"
SUMMARY_FILE="$SANDBOX/summary.md"
HEAD_SHA=$(cat "$SANDBOX/head_sha")

if [ "$DRY_RUN" = "true" ]; then
  echo "DRY RUN — would post the following:"
  echo "--- inline findings ---"
  jq . "$FINDINGS_FILE"
  echo "--- summary ---"
  cat "$SUMMARY_FILE"
  jq -r 'length' "$FINDINGS_FILE" > "$SANDBOX/posted_inline_count"
  echo "0" > "$SANDBOX/failed_posts_count"
  echo "" > "$SANDBOX/summary_url"
  exit 0
fi

echo "Deleting prior bot inline comments with marker..."
gh api --paginate "repos/$REPO/pulls/$PR_NUMBER/comments" \
  | jq -r --arg marker "$MARKER" \
      '.[] | select(.user.type == "Bot" and (.body | contains($marker))) | .id' \
  | while IFS= read -r cid; do
      [ -z "$cid" ] && continue
      gh api -X DELETE "repos/$REPO/pulls/comments/$cid" >/dev/null || \
        echo "warn: could not delete inline comment $cid" >&2
    done

echo "Deleting prior bot summary comments with marker..."
gh api --paginate "repos/$REPO/issues/$PR_NUMBER/comments" \
  | jq -r --arg marker "$MARKER" \
      '.[] | select(.user.type == "Bot" and (.body | contains($marker))) | .id' \
  | while IFS= read -r cid; do
      [ -z "$cid" ] && continue
      gh api -X DELETE "repos/$REPO/issues/comments/$cid" >/dev/null || \
        echo "warn: could not delete issue comment $cid" >&2
    done

posted=0
failed=0
finding_count=$(jq -r 'length' "$FINDINGS_FILE")
echo "Posting $finding_count inline comments..."
for i in $(seq 0 $((finding_count - 1))); do
  payload=$(jq -c --arg sha "$HEAD_SHA" --arg marker "$MARKER" --argjson i "$i" '
    .[$i] as $f
    | {
        commit_id: $sha,
        path: $f.path,
        side: "RIGHT",
        line: $f.line,
        body: ($marker + "\n**[" + $f.severity + "/" + $f.category + "]** " + $f.body)
      }
    | if ($f.end_line // null) != null and $f.end_line > $f.line
      then . + {start_line: $f.line, line: $f.end_line, start_side: "RIGHT"}
      else .
      end
  ' "$FINDINGS_FILE")
  if echo "$payload" | gh api -X POST "repos/$REPO/pulls/$PR_NUMBER/comments" \
       --input - >/dev/null 2>"$SANDBOX/post_err.$i"; then
    posted=$((posted + 1))
  else
    failed=$((failed + 1))
    echo "warn: failed to post finding $i:" >&2
    cat "$SANDBOX/post_err.$i" >&2
  fi
done

echo "Posting summary comment..."
body=$(printf '%s\n## aider-code-review\n\n%s\n' "$MARKER" "$(cat "$SUMMARY_FILE")")
summary_url=$(jq -nc --arg body "$body" '{body: $body}' \
  | gh api -X POST "repos/$REPO/issues/$PR_NUMBER/comments" --input - \
  | jq -r '.html_url')

echo "$posted" > "$SANDBOX/posted_inline_count"
echo "$failed" > "$SANDBOX/failed_posts_count"
echo "$summary_url" > "$SANDBOX/summary_url"
echo "Done. Posted $posted inline, $failed failed. Summary: $summary_url"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/post_comments.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/post_comments.sh
git commit -m "feat: add post_comments.sh gh wrapper"
```

---

## Task 10: `run_review.sh` — orchestrator

**Files:**
- Create: `scripts/run_review.sh`

The composite action's entry point. Ties everything together. Pure glue; exercised end-to-end by `self-test.yml`.

Contract: reads env vars set by `action.yml`. Creates sandbox, runs the first-time contributor gate, fetches context, runs aider, extracts JSON + summary, filters findings, posts comments. Sets GitHub Actions outputs via `$GITHUB_OUTPUT`.

- [ ] **Step 1: Write `scripts/run_review.sh`**

```bash
#!/usr/bin/env bash
# aider-code-review orchestrator. Called by action.yml.
# Required env vars (set by action.yml):
#   DEEPSEEK_API_KEY, GH_TOKEN, REPO, PR_NUMBER,
#   MODEL, EDITOR_MODEL, MAX_FILES, EXCLUDE_PATTERNS,
#   FIRST_TIME_GATE_LABEL, AIDER_VERSION, DRY_RUN, ACTION_DIR
set -euo pipefail

: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY is required}"
: "${GH_TOKEN:?GH_TOKEN is required}"
: "${REPO:?REPO is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${MODEL:=deepseek/deepseek-reasoner}"
: "${EDITOR_MODEL:=deepseek/deepseek-chat}"
: "${MAX_FILES:=20}"
: "${EXCLUDE_PATTERNS:=}"
: "${FIRST_TIME_GATE_LABEL:=}"
: "${AIDER_VERSION:=}"
: "${DRY_RUN:=false}"
: "${ACTION_DIR:?ACTION_DIR is required}"

export GH_TOKEN

SANDBOX="${RUNNER_TEMP:-/tmp}/aider-review-${GITHUB_RUN_ID:-local}"
rm -rf "$SANDBOX"
mkdir -p "$SANDBOX"
echo "Sandbox: $SANDBOX"

# --- Install aider (from PyPI, before any PR data lands on disk) ---
if [ -n "$AIDER_VERSION" ]; then
  pip install --user --quiet "aider-chat==$AIDER_VERSION"
else
  pip install --user --quiet "aider-chat"
fi
export PATH="$HOME/.local/bin:$PATH"
aider --version

# --- Fetch PR context ---
SANDBOX="$SANDBOX" REPO="$REPO" PR_NUMBER="$PR_NUMBER" \
  MAX_FILES="$MAX_FILES" EXCLUDE_PATTERNS="$EXCLUDE_PATTERNS" \
  "$ACTION_DIR/scripts/fetch_pr_context.sh"

# --- First-time contributor gate ---
if [ -n "$FIRST_TIME_GATE_LABEL" ]; then
  assoc=$(cat "$SANDBOX/author_association")
  case "$assoc" in
    FIRST_TIME_CONTRIBUTOR|FIRST_TIMER|NONE)
      has_label=$(gh api "repos/$REPO/issues/$PR_NUMBER/labels" \
        --jq "any(.name == \"$FIRST_TIME_GATE_LABEL\")")
      if [ "$has_label" != "true" ]; then
        echo "First-time contributor gate: author_association=$assoc and label '$FIRST_TIME_GATE_LABEL' not present. Skipping review."
        echo "skipped=true" >> "${GITHUB_OUTPUT:-/dev/null}"
        exit 0
      fi
      ;;
  esac
fi

# --- Run aider ---
cd "$SANDBOX"
git init --quiet . >/dev/null

read_args=( --read pr.diff )
while IFS= read -r path; do
  [ -z "$path" ] && continue
  [ -f "head/$path" ] && read_args+=( --read "head/$path" )
done < "$SANDBOX/included_files.txt"

set +e
DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" aider \
  --architect \
  --model "$MODEL" \
  --editor-model "$EDITOR_MODEL" \
  --no-auto-commits --no-git --yes-always --no-stream \
  --no-show-model-warnings --no-check-update \
  "${read_args[@]}" \
  --message "$(cat "$ACTION_DIR/prompts/architect.md")" \
  > "$SANDBOX/aider.stdout" 2> "$SANDBOX/aider.stderr"
aider_rc=$?
set -e
echo "aider exit code: $aider_rc"

# --- Scrub secrets from aider stdout before any further processing ---
python3 - <<PY
import os, re
path = os.environ["SANDBOX"] + "/aider.stdout"
text = open(path, encoding="utf-8", errors="replace").read()
for var in ("DEEPSEEK_API_KEY", "GH_TOKEN"):
    val = os.environ.get(var, "")
    if val:
        text = text.replace(val, "[REDACTED]")
open(path, "w", encoding="utf-8").write(text)
PY

# --- Extract JSON findings ---
findings_json="$SANDBOX/findings_raw.json"
if "$ACTION_DIR/scripts/extract_json.py" "$SANDBOX/aider.stdout" > "$findings_json"; then
  extract_status=ok
else
  rc=$?
  extract_status=fail
  echo "extract_json exit: $rc" >&2
  echo "[]" > "$findings_json"
fi

# --- Filter findings (hallucination guard) ---
"$ACTION_DIR/scripts/filter_findings.py" \
  "$findings_json" "$SANDBOX/pr.diff" \
  > "$SANDBOX/findings.json" 2> "$SANDBOX/filter.err"
dropped=$(grep -oE 'dropped [0-9]+' "$SANDBOX/filter.err" | awk '{print $2}')
dropped="${dropped:-0}"
final_count=$(jq -r 'length' "$SANDBOX/findings.json")
echo "findings: $final_count surviving, $dropped dropped"

# --- Extract summary ---
if "$ACTION_DIR/scripts/extract_summary.py" "$SANDBOX/aider.stdout" \
     > "$SANDBOX/summary.md" 2>/dev/null; then
  :
else
  total=$(cat "$SANDBOX/total_changed_files")
  included=$(cat "$SANDBOX/included_files_count")
  if [ "$final_count" -eq 0 ]; then
    echo "Reviewed $included of $total changed files. No high-signal issues found." > "$SANDBOX/summary.md"
  else
    echo "Reviewed $included of $total changed files. Surfaced $final_count finding(s)." > "$SANDBOX/summary.md"
  fi
fi

# Append warning if aider failed.
if [ "$aider_rc" -ne 0 ]; then
  {
    echo
    echo "⚠️ Review incomplete (aider exit $aider_rc)."
    echo
    echo "<details><summary>aider stderr (tail)</summary>"
    echo
    echo '```'
    tail -n 50 "$SANDBOX/aider.stderr"
    echo '```'
    echo
    echo "</details>"
  } >> "$SANDBOX/summary.md"
fi

# Append warning if JSON parse failed.
if [ "$extract_status" = "fail" ]; then
  {
    echo
    echo "⚠️ Model produced unstructured output."
    echo
    echo "<details><summary>raw aider output (tail)</summary>"
    echo
    echo '```'
    tail -n 80 "$SANDBOX/aider.stdout"
    echo '```'
    echo
    echo "</details>"
  } >> "$SANDBOX/summary.md"
fi

# Append "skipped files" note if applicable.
total=$(cat "$SANDBOX/total_changed_files")
included=$(cat "$SANDBOX/included_files_count")
if [ "$total" -gt "$included" ]; then
  skipped=$((total - included))
  echo "" >> "$SANDBOX/summary.md"
  echo "Note: $skipped file(s) skipped (max_files=$MAX_FILES)." >> "$SANDBOX/summary.md"
fi

# --- Post comments ---
SANDBOX="$SANDBOX" REPO="$REPO" PR_NUMBER="$PR_NUMBER" DRY_RUN="$DRY_RUN" \
  "$ACTION_DIR/scripts/post_comments.sh"

# --- Set action outputs ---
posted=$(cat "$SANDBOX/posted_inline_count")
failed=$(cat "$SANDBOX/failed_posts_count")
summary_url=$(cat "$SANDBOX/summary_url")
{
  echo "findings_count=$final_count"
  echo "dropped_hallucinations_count=$dropped"
  echo "posted_inline_count=$posted"
  echo "failed_posts_count=$failed"
  echo "summary_comment_url=$summary_url"
} >> "${GITHUB_OUTPUT:-/dev/stdout}"
```

- [ ] **Step 2: Make executable**

```bash
chmod +x scripts/run_review.sh
```

- [ ] **Step 3: Commit**

```bash
git add scripts/run_review.sh
git commit -m "feat: add run_review.sh orchestrator"
```

---

## Task 11: `action.yml` — composite action manifest

**Files:**
- Create: `action.yml`

- [ ] **Step 1: Write `action.yml`**

```yaml
name: aider-code-review
description: Agentic PR review using aider with DeepSeek as the backend model.
author: motsognirr
branding:
  icon: eye
  color: blue

inputs:
  deepseek_api_key:
    description: DeepSeek API key (passed to aider as DEEPSEEK_API_KEY).
    required: true
  github_token:
    description: GitHub token with `pull-requests: write` and `contents: read`.
    required: true
  pr_number:
    description: Pull request number. Defaults to the event payload.
    required: false
    default: ${{ github.event.pull_request.number }}
  repo:
    description: Repository in `owner/name` form. Defaults to the workflow repo.
    required: false
    default: ${{ github.repository }}
  model:
    description: aider architect model.
    required: false
    default: deepseek/deepseek-reasoner
  editor_model:
    description: aider editor model (used in --architect mode).
    required: false
    default: deepseek/deepseek-chat
  max_files:
    description: Maximum number of changed files to fetch for context.
    required: false
    default: "20"
  exclude_patterns:
    description: Newline-separated glob patterns to exclude from context.
    required: false
    default: |
      **/*.lock
      **/dist/**
      **/node_modules/**
      **/*.min.*
      **/generated/**
      **/*.svg
      **/*.png
      **/*.jpg
  first_time_contributor_gate_label:
    description: If set, gate review on this label for first-time contributors.
    required: false
    default: ""
  aider_version:
    description: aider-chat version to install (defaults to latest).
    required: false
    default: ""
  dry_run:
    description: If "true", print findings to job log instead of posting.
    required: false
    default: "false"

outputs:
  findings_count:
    description: Number of surviving findings posted (or would-be in dry_run).
    value: ${{ steps.review.outputs.findings_count }}
  dropped_hallucinations_count:
    description: Findings dropped by the hallucination guard.
    value: ${{ steps.review.outputs.dropped_hallucinations_count }}
  posted_inline_count:
    description: Inline comments successfully posted.
    value: ${{ steps.review.outputs.posted_inline_count }}
  failed_posts_count:
    description: Inline comments that failed to post.
    value: ${{ steps.review.outputs.failed_posts_count }}
  summary_comment_url:
    description: URL of the posted summary comment.
    value: ${{ steps.review.outputs.summary_comment_url }}

runs:
  using: composite
  steps:
    - name: Run aider review
      id: review
      shell: bash
      env:
        DEEPSEEK_API_KEY: ${{ inputs.deepseek_api_key }}
        GH_TOKEN: ${{ inputs.github_token }}
        REPO: ${{ inputs.repo }}
        PR_NUMBER: ${{ inputs.pr_number }}
        MODEL: ${{ inputs.model }}
        EDITOR_MODEL: ${{ inputs.editor_model }}
        MAX_FILES: ${{ inputs.max_files }}
        EXCLUDE_PATTERNS: ${{ inputs.exclude_patterns }}
        FIRST_TIME_GATE_LABEL: ${{ inputs.first_time_contributor_gate_label }}
        AIDER_VERSION: ${{ inputs.aider_version }}
        DRY_RUN: ${{ inputs.dry_run }}
        ACTION_DIR: ${{ github.action_path }}
      run: |
        bash "${{ github.action_path }}/scripts/run_review.sh"
```

- [ ] **Step 2: Commit**

```bash
git add action.yml
git commit -m "feat: add composite action manifest"
```

---

## Task 12: `.github/workflows/ci.yml` — pytest on push

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Write `.github/workflows/ci.yml`**

```yaml
name: ci

on:
  push:
    branches: [main]
  pull_request:

jobs:
  pytest:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pytest
      - run: python -m pytest tests/ -v
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: run pytest on push and PR"
```

---

## Task 13: `.github/workflows/self-test.yml` — exercise action on own PRs

**Files:**
- Create: `.github/workflows/self-test.yml`

- [ ] **Step 1: Write `.github/workflows/self-test.yml`**

```yaml
name: self-test

on:
  pull_request_target:
    types: [opened, synchronize, reopened]

permissions:
  pull-requests: write
  contents: read

jobs:
  review:
    runs-on: [self-hosted, macOS]
    steps:
      - uses: actions/checkout@v4
        with:
          ref: ${{ github.event.pull_request.base.sha }}
      - uses: ./
        with:
          deepseek_api_key: ${{ secrets.DEEPSEEK_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          dry_run: "true"
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/self-test.yml
git commit -m "ci: add self-test workflow (dry_run on own PRs)"
```

---

## Task 14: `README.md` — full documentation

**Files:**
- Modify: `README.md` (replace skeleton)

- [ ] **Step 1: Replace `README.md` with full docs**

````markdown
# aider-code-review

Reusable GitHub Action that performs agentic PR review using
[aider](https://aider.chat) with DeepSeek as the backend model. Posts
inline `path:line` comments and a top-level summary. Fork-safe: PRs from
forks are reviewed without exposing secrets to PR-controlled code.

## Quick start

In any consumer repo, add `.github/workflows/aider-review.yml`:

```yaml
name: aider PR review
on:
  pull_request_target:
    types: [opened, synchronize, reopened]
permissions:
  pull-requests: write
  contents: read
jobs:
  review:
    runs-on: [self-hosted, macOS]
    steps:
      - uses: motsognirr/aider-code-review@v1
        with:
          deepseek_api_key: ${{ secrets.DEEPSEEK_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

Set the `DEEPSEEK_API_KEY` secret in the consumer repo (or org).

## Runner prerequisites

Self-hosted macOS runners must have:

```bash
brew install gh jq python@3.12
```

aider is installed by the action at runtime.

## Fork-safety model

The action is designed for `pull_request_target` so that secrets are
available. To prevent attacker-controlled PR code from executing with
those secrets:

- The action does NOT run `actions/checkout` of the PR head.
- It fetches the diff and head file blobs via the GitHub API, into a
  sandboxed `$RUNNER_TEMP/aider-review-<run_id>` directory.
- aider is installed from PyPI before any PR data is fetched.
- aider runs with `--no-auto-commits --no-git --yes-always` and
  read-only file mounts; it cannot write back or shell out.
- All PR-derived strings (paths, titles, bodies) are passed as data,
  never `eval`'d.
- Optional `first_time_contributor_gate_label` requires a maintainer
  to apply the named label before first-time contributors get reviewed.

### Do NOT do this in your caller workflow

```yaml
# BAD: this checks out PR-author code into a tree where secrets exist.
- uses: actions/checkout@v4
  with:
    ref: ${{ github.event.pull_request.head.sha }}
- run: pip install -r requirements.txt  # arbitrary code from PR
- uses: motsognirr/aider-code-review@v1
  with:
    deepseek_api_key: ${{ secrets.DEEPSEEK_API_KEY }}
```

The action does its own sandboxed setup; the caller should add no
checkout, install, or test steps before invoking it.

## Inputs

| Input | Required | Default | Notes |
|---|---|---|---|
| `deepseek_api_key` | yes | — | Passed to aider as `DEEPSEEK_API_KEY` |
| `github_token` | yes | — | Needs `pull-requests: write`, `contents: read` |
| `pr_number` | no | event payload | Override for `workflow_dispatch` |
| `repo` | no | workflow repo | Override for cross-repo callers |
| `model` | no | `deepseek/deepseek-reasoner` | aider architect model |
| `editor_model` | no | `deepseek/deepseek-chat` | aider editor model |
| `max_files` | no | `20` | Cap on fetched changed files |
| `exclude_patterns` | no | sane defaults | Newline-separated globs |
| `first_time_contributor_gate_label` | no | `""` | If set, gates review on label |
| `aider_version` | no | latest | Pin for reproducibility |
| `dry_run` | no | `"false"` | Print findings to job log; skip posting |

## Outputs

| Output | Description |
|---|---|
| `findings_count` | Surviving findings posted (or would-be in dry_run) |
| `dropped_hallucinations_count` | Findings dropped by the guard |
| `posted_inline_count` | Inline comments successfully posted |
| `failed_posts_count` | Inline POSTs that errored |
| `summary_comment_url` | URL of the posted summary comment |

## How it works

1. Sandboxed setup: install aider from PyPI; fetch the PR diff,
   metadata, and head file blobs via `gh api`.
2. Run aider in `--architect` mode against the diff plus the head
   versions of changed files (read-only), with a prompt asking for
   structured JSON findings plus a `## Summary` section.
3. Parse the JSON. Drop any finding whose `path:line` isn't a `+`
   line in the PR diff (hallucination guard).
4. Delete any previous bot comments tagged with the action's marker
   (idempotency on `synchronize`). Post inline comments and a summary.

## Releases

- `v1.x.y` — semver releases.
- `v1` — moving alias updated on every minor/patch release.
- Action is also pinnable by full SHA.

## License

MIT.
````

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: full README with quick start, fork-safety, inputs/outputs"
```

---

## Task 15: `.github/workflows/release.yml` — moving `v1` alias

**Files:**
- Create: `.github/workflows/release.yml`

When a `v1.x.y` tag is pushed, force-update the `v1` tag to point at the same commit.

- [ ] **Step 1: Write `.github/workflows/release.yml`**

```yaml
name: release

on:
  push:
    tags:
      - "v1.*"

permissions:
  contents: write

jobs:
  update-v1-alias:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Update moving v1 tag
        run: |
          git tag -f v1
          git push origin v1 --force
```

- [ ] **Step 2: Commit**

```bash
git add .github/workflows/release.yml
git commit -m "ci: update moving v1 alias on v1.x.y tag push"
```

---

## Task 16: Push to remote, tag v1.0.0

This is a manual final step. The agent should pause and ask the human
to confirm before pushing and tagging.

- [ ] **Step 1: Verify everything passes locally**

```bash
python3 -m pytest tests/ -v
```

Expected: all green.

- [ ] **Step 2: Push main**

```bash
git push -u origin main
```

- [ ] **Step 3: Tag v1.0.0 and push the tag**

```bash
git tag -a v1.0.0 -m "Initial release: aider-code-review v1.0.0"
git push origin v1.0.0
```

The `release.yml` workflow runs on `v1.*` tag push and force-updates the
moving `v1` tag.

- [ ] **Step 4: Verify the v1 alias was created**

```bash
git fetch --tags
git tag -l v1
```

Expected: `v1` present, pointing at the same SHA as `v1.0.0`.

- [ ] **Step 5: Verify the release.yml run on GitHub**

```bash
gh run list --workflow=release.yml --limit 1
```

Expected: most recent run is `completed` / `success`.

---

## Out of scope (follow-up tasks)

These were excluded from this session per the scope decision:

1. **5-PR benchmark against the existing Claude reviewer in `motsognirr/olmlx`.** Pick 5 recent merged PRs, run the action against each (with `dry_run: true` and the action checked out at a feature branch), record the findings, compare to historical Claude-reviewer comments. Document parity in a `BENCHMARK.md` file.
2. **Replace `.github/workflows/claude-code-review.yml` in `motsognirr/olmlx`** with a thin caller workflow that uses `motsognirr/aider-code-review@v1`. Rename to `.github/workflows/aider-code-review.yml`. Delete the Anthropic OAuth secret if no longer referenced elsewhere.
