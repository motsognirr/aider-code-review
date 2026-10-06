"""End-to-end coverage of post_comments.sh against a stubbed `gh`.

Two behaviours are pinned here:

* the delete pass only touches this reviewer's own comments (the cross-job
  wipe), and
* zero findings posts zero comments, including where `seq` counts *down* for
  an empty range as BSD/macOS seq does.
"""

import json
import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "post_comments.sh"

GPT_MODEL = "openai/gpt-5.6-luna"
GPT = "<!-- aider-code-review:openai/gpt-5.6-luna -->"
DEEPSEEK = "<!-- aider-code-review:deepseek/deepseek-flash -->"
LEGACY = "<!-- aider-code-review -->"

GH_STUB = r"""#!/usr/bin/env bash
if [[ "$1" == "api" && "$*" == *"--paginate"* ]]; then
  echo "LIST ${@: -1}" >> "$CALL_LOG"; cat "$FAKE_COMMENTS"; exit 0
fi
if [[ "$*" == *"-X DELETE"* ]]; then echo "DELETE ${@: -1}" >> "$CALL_LOG"; exit 0; fi
if [[ "$*" == *"-X POST"* ]]; then
  body=$(cat)
  target="pulls"; [[ "$*" == *"issues"* ]] && target="issues"
  if [[ "$target" == "issues" && -n "${FAIL_SUMMARY_POST:-}" ]]; then exit 1; fi
  echo "POST $target $body" >> "$CALL_LOG"
  # Like GitHub: a posted comment shows up in the next listing, Bot-authored.
  id=$((9000 + $(wc -l < "$CALL_LOG")))
  jq --argjson id "$id" --arg body "$(jq -r .body <<< "$body")" \
    '. + [{id: $id, user: {type: "Bot"}, body: $body}]' "$FAKE_COMMENTS" > "$FAKE_COMMENTS.new"
  mv "$FAKE_COMMENTS.new" "$FAKE_COMMENTS"
  echo "{\"html_url\":\"https://example.invalid/c/$id\"}"
  exit 0
fi
exit 0
"""

# BSD/macOS `seq 0 -1` emits "0\n-1" instead of nothing, so an empty findings
# list would post bogus comments. GNU seq emits nothing, which is why this has
# to be stubbed rather than left to the host.
SEQ_STUB = r"""#!/usr/bin/env bash
start=$1; end=$2
if [ "$end" -lt "$start" ]; then
  for ((i = start; i >= end; i--)); do echo "$i"; done
else
  for ((i = start; i <= end; i++)); do echo "$i"; done
fi
"""


@pytest.fixture
def harness(tmp_path):
    binp = tmp_path / "bin"
    binp.mkdir()
    for name, src in (("gh", GH_STUB), ("seq", SEQ_STUB)):
        p = binp / name
        p.write_text(src)
        p.chmod(0o755)

    sandbox = tmp_path / "sandbox"
    sandbox.mkdir()
    (sandbox / "head_sha").write_text("deadbeef\n")
    (sandbox / "summary.md").write_text("a summary\n")

    call_log = tmp_path / "calls.log"
    call_log.touch()
    comments = tmp_path / "comments.json"
    comments.write_text("[]")

    def run(findings, comment_list=None, model=GPT_MODEL, extra_env=None, expect_rc=0):
        (sandbox / "findings.json").write_text(json.dumps(findings))
        comments.write_text(json.dumps(comment_list or []))
        env = {
            **os.environ,
            "PATH": f"{binp}:{os.environ['PATH']}",
            "FAKE_COMMENTS": str(comments),
            "CALL_LOG": str(call_log),
            "REPO": "o/r",
            "PR_NUMBER": "1",
            "SANDBOX": str(sandbox),
            "MODEL": model,
            **(extra_env or {}),
        }
        proc = subprocess.run(
            ["bash", str(SCRIPT)], env=env, capture_output=True, text=True
        )
        assert (proc.returncode == 0) == (expect_rc == 0), proc.stderr
        calls = call_log.read_text().splitlines()
        call_log.write_text("")
        return calls

    return run


def bot(cid, body, user_type="Bot"):
    return {"id": cid, "user": {"type": user_type}, "body": body}


def test_zero_findings_posts_no_inline_comments(harness):
    """`seq 0 -1` counting down must not turn an empty findings list into posts."""
    calls = harness([])
    assert [c for c in calls if c.startswith("POST pulls")] == []


def test_zero_findings_still_posts_the_summary(harness):
    calls = harness([])
    assert len([c for c in calls if c.startswith("POST issues")]) == 1


def test_each_finding_is_posted_once(harness):
    findings = [
        {"path": "a.py", "line": 3, "severity": "medium", "category": "bug", "body": "one"},
        {"path": "b.py", "line": 7, "severity": "low", "category": "style", "body": "two"},
    ]
    posts = [c for c in harness(findings) if c.startswith("POST pulls")]
    assert len(posts) == 2


def test_posted_comments_carry_the_scoped_marker(harness):
    findings = [
        {"path": "a.py", "line": 3, "severity": "medium", "category": "bug", "body": "one"}
    ]
    posts = [c for c in harness(findings) if c.startswith("POST pulls")]
    assert GPT in posts[0]
    assert f"{LEGACY}\n" not in posts[0]


def test_delete_pass_spares_the_other_reviewers_comments(harness):
    comments = [
        bot(101, GPT + "\nmy own prior finding"),
        bot(202, DEEPSEEK + "\nthe other job's fresh finding"),
        bot(303, LEGACY + "\nlegacy unscoped"),
        bot(404, GPT + " quoted by a human", user_type="User"),
    ]
    deleted = {c.rsplit("/", 1)[-1] for c in harness([], comments) if c.startswith("DELETE")}
    assert deleted == {"101", "303"}


def test_unbuildable_finding_is_a_failed_post_not_an_abort(harness):
    # A finding the payload builder can't render (numeric severity is a jq type
    # error) must not stop the run after old comments were already deleted.
    findings = [
        {"path": "a.py", "line": 3, "severity": 3, "category": "bug", "body": "bad"},
        {"path": "b.py", "line": 7, "severity": "low", "category": "bug", "body": "ok"},
    ]
    calls = harness(findings)
    assert len([c for c in calls if c.startswith("POST pulls")]) == 1
    assert len([c for c in calls if c.startswith("POST issues")]) == 1


STALE = [bot(101, GPT + "\nmy prior finding"), bot(102, GPT + "\nmy prior summary")]
ONE = [{"path": "a.py", "line": 3, "severity": "medium", "category": "bug", "body": "one"}]


def test_new_comments_are_posted_before_old_ones_are_deleted(harness):
    # If posting fails partway, the PR must still carry the previous review
    # rather than nothing.
    calls = harness(ONE, STALE)
    kinds = [c.split()[0] for c in calls]
    last_post = max(i for i, k in enumerate(kinds) if k == "POST")
    first_delete = kinds.index("DELETE")
    assert last_post < first_delete


def test_only_the_prior_comments_are_deleted_not_the_fresh_ones(harness):
    # The stale set is captured before posting: the fresh comments carry the
    # same marker and would otherwise be deleted the moment they appear.
    calls = harness(ONE, STALE)
    deleted = {c.rsplit("/", 1)[-1] for c in calls if c.startswith("DELETE")}
    assert deleted == {"101", "102"}


def test_failed_summary_post_keeps_the_previous_review(harness):
    calls = harness(ONE, STALE, extra_env={"FAIL_SUMMARY_POST": "1"}, expect_rc=1)
    assert [c for c in calls if c.startswith("DELETE")] == []


def test_failed_summary_post_posts_no_inline_comments(harness):
    # The summary goes first: if it fails, nothing new is up, so the previous
    # review is left exactly as it was rather than duplicated alongside.
    calls = harness(ONE, STALE, extra_env={"FAIL_SUMMARY_POST": "1"}, expect_rc=1)
    assert [c for c in calls if c.startswith("POST pulls")] == []
