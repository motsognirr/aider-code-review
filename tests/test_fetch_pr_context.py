"""fetch_pr_context.sh against a stubbed `gh`.

The stub mirrors real `gh pr diff`: with `--patch` it returns the per-commit
format-patch series (the same file appearing once per commit, with line
numbers from intermediate states); without it, the single combined diff of
base..head. Findings are anchored to head line numbers, so only the combined
diff is a valid input for the model and the hallucination guard.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "fetch_pr_context.sh"

COMBINED = """\
diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,3 @@
 x = 1
+y = 2
+z = 3
"""

PATCH_SERIES = """\
From 1111111111111111111111111111111111111111 Mon Sep 17 00:00:00 2001
Subject: [PATCH 1/2] add y

diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,1 +1,2 @@
 x = 1
+y = 2
--
From 2222222222222222222222222222222222222222 Mon Sep 17 00:00:00 2001
Subject: [PATCH 2/2] add z

diff --git a/a.py b/a.py
--- a/a.py
+++ b/a.py
@@ -1,2 +1,3 @@
 x = 1
 y = 2
+z = 3
--
"""

GH_STUB = r"""#!/usr/bin/env bash
if [[ "$1 $2" == "pr diff" ]]; then
  if [[ "$*" == *"--patch"* ]]; then cat "$FAKE_PATCH"; else cat "$FAKE_COMBINED"; fi
  exit 0
fi
if [[ "$*" == *"/files"* ]]; then cat "$FAKE_FILES"; exit 0; fi
if [[ "$*" == *"/contents/"* ]]; then echo 'eA=='; exit 0; fi
if [[ "$1" == "api" ]]; then
  echo '{"head":{"sha":"h"},"base":{"sha":"b"},"author_association":"MEMBER"}'
  exit 0
fi
exit 1
"""


# The action's default `exclude_patterns` (action.yml).
DEFAULT_EXCLUDES = """\
**/*.lock
**/dist/**
**/node_modules/**
**/*.min.*
**/generated/**
**/*.svg
**/*.png
**/*.jpg
"""


@pytest.fixture
def fetch(tmp_path):
    binp = tmp_path / "bin"
    binp.mkdir()
    gh = binp / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(0o755)
    (tmp_path / "combined.diff").write_text(COMBINED)
    (tmp_path / "series.patch").write_text(PATCH_SERIES)
    files = tmp_path / "files.json"
    sandbox = tmp_path / "sandbox"

    def run(changed=(), exclude_patterns="", max_files=20):
        files.write_text(json.dumps([{"filename": f, "status": "modified"} for f in changed]))
        env = {
            **os.environ,
            "PATH": f"{binp}:{os.environ['PATH']}",
            "FAKE_COMBINED": str(tmp_path / "combined.diff"),
            "FAKE_PATCH": str(tmp_path / "series.patch"),
            "FAKE_FILES": str(files),
            "REPO": "o/r",
            "PR_NUMBER": "1",
            "SANDBOX": str(sandbox),
            "EXCLUDE_PATTERNS": exclude_patterns,
            "MAX_FILES": str(max_files),
        }
        proc = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
        assert proc.returncode == 0, proc.stderr
        return sandbox

    return run


def included(sandbox):
    return (sandbox / "included_files.txt").read_text().splitlines()


def test_pr_diff_is_the_combined_diff_not_a_per_commit_series(fetch):
    sandbox = fetch()
    assert (sandbox / "pr.diff").read_text() == COMBINED


def test_default_excludes_match_files_at_the_repo_root(fetch):
    # `**/` must also match zero directories, as in gitignore: a root-level
    # Cargo.lock or dist/ is as much noise as a nested one.
    root_level = ["Cargo.lock", "dist/app.js", "node_modules/x/y.js", "logo.svg",
                  "app.min.js", "generated/api.py"]
    sandbox = fetch(["src/a.py", *root_level], DEFAULT_EXCLUDES)
    assert included(sandbox) == ["src/a.py"]


def test_default_excludes_still_match_nested_files(fetch):
    nested = ["sub/Cargo.lock", "web/dist/app.js", "a/b/logo.svg"]
    sandbox = fetch(["src/a.py", *nested], DEFAULT_EXCLUDES)
    assert included(sandbox) == ["src/a.py"]


def test_exclude_does_not_match_a_mere_name_prefix(fetch):
    sandbox = fetch(["distro/main.py", "src/distance.py"], DEFAULT_EXCLUDES)
    assert included(sandbox) == ["distro/main.py", "src/distance.py"]
