"""fetch_pr_context.sh against a stubbed `gh`.

The stub mirrors real `gh pr diff`: with `--patch` it returns the per-commit
format-patch series (the same file appearing once per commit, with line
numbers from intermediate states); without it, the single combined diff of
base..head. Findings are anchored to head line numbers, so only the combined
diff is a valid input for the model and the hallucination guard.
"""

import os
import subprocess
from pathlib import Path

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
if [[ "$*" == *"/files"* ]]; then echo '[]'; exit 0; fi
if [[ "$1" == "api" ]]; then
  echo '{"head":{"sha":"h"},"base":{"sha":"b"},"author_association":"MEMBER"}'
  exit 0
fi
exit 1
"""


def test_pr_diff_is_the_combined_diff_not_a_per_commit_series(tmp_path):
    binp = tmp_path / "bin"
    binp.mkdir()
    gh = binp / "gh"
    gh.write_text(GH_STUB)
    gh.chmod(0o755)
    (tmp_path / "combined.diff").write_text(COMBINED)
    (tmp_path / "series.patch").write_text(PATCH_SERIES)
    sandbox = tmp_path / "sandbox"

    env = {
        **os.environ,
        "PATH": f"{binp}:{os.environ['PATH']}",
        "FAKE_COMBINED": str(tmp_path / "combined.diff"),
        "FAKE_PATCH": str(tmp_path / "series.patch"),
        "REPO": "o/r",
        "PR_NUMBER": "1",
        "SANDBOX": str(sandbox),
    }
    proc = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr

    assert (sandbox / "pr.diff").read_text() == COMBINED
