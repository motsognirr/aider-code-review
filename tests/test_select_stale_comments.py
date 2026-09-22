"""The delete filter must only match this reviewer's own comments.

Regression coverage for the cross-job wipe: two jobs running the action on one
PR with different models both stamped the same marker, so whichever finished
last deleted the other's findings.
"""

import json
import subprocess
from pathlib import Path

import pytest

FILTER = Path(__file__).resolve().parent.parent / "scripts" / "select_stale_comments.jq"

LEGACY = "<!-- aider-code-review -->"
GPT = "<!-- aider-code-review:openai/gpt-5.6-luna -->"
DEEPSEEK = "<!-- aider-code-review:deepseek/deepseek-flash -->"


def bot(cid: int, body: str, user_type: str = "Bot") -> dict:
    return {"id": cid, "user": {"type": user_type}, "body": body}


def select(comments: list[dict], marker: str, legacy: bool = True) -> list[int]:
    out = subprocess.run(
        [
            "jq", "-r",
            "--arg", "marker", marker,
            "--arg", "legacy_marker", LEGACY,
            "--argjson", "sweep_legacy", "true" if legacy else "false",
            "-f", str(FILTER),
        ],
        input=json.dumps(comments),
        capture_output=True,
        text=True,
        check=True,
    )
    return [int(line) for line in out.stdout.split() if line.strip()]


def test_selects_own_scoped_comments():
    comments = [bot(1, GPT + "\nfinding")]
    assert select(comments, GPT) == [1]


def test_does_not_select_another_models_comments():
    """The bug: gpt-review deleted deepseek-review's findings seconds after they posted."""
    comments = [bot(1, GPT + "\nmine"), bot(2, DEEPSEEK + "\ntheirs")]
    assert select(comments, GPT) == [1]
    assert select(comments, DEEPSEEK) == [2]


def test_concurrent_jobs_select_disjoint_sets():
    comments = [bot(1, GPT + "\na"), bot(2, DEEPSEEK + "\nb"), bot(3, GPT + "\nc")]
    gpt_ids, ds_ids = select(comments, GPT), select(comments, DEEPSEEK)
    assert set(gpt_ids).isdisjoint(ds_ids)
    assert sorted(gpt_ids + ds_ids) == [1, 2, 3]


def test_sweeps_legacy_unscoped_comments():
    comments = [bot(1, LEGACY + "\nold run")]
    assert select(comments, GPT) == [1]


def test_legacy_sweep_can_be_disabled():
    comments = [bot(1, LEGACY + "\nold run"), bot(2, GPT + "\nmine")]
    assert select(comments, GPT, legacy=False) == [2]


def test_ignores_non_bot_comments():
    """A human quoting the marker must never have their comment deleted."""
    comments = [bot(1, GPT + "\nquoted by a person", user_type="User")]
    assert select(comments, GPT) == []


def test_ignores_unrelated_comments():
    comments = [bot(1, "looks good to me")]
    assert select(comments, GPT) == []


def test_empty_list():
    assert select([], GPT) == []
