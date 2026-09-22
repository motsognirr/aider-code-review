"""Marker construction: one comment namespace per reviewer invocation."""

import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "comment_marker.py"

LEGACY = "<!-- aider-code-review -->"


def marker(key: str) -> str:
    out = subprocess.run(
        [sys.executable, str(SCRIPT), key],
        capture_output=True,
        text=True,
        check=True,
    )
    return out.stdout.strip()


def test_marker_is_scoped_by_key():
    assert marker("openai/gpt-5.6-luna") == "<!-- aider-code-review:openai/gpt-5.6-luna -->"


def test_distinct_models_get_distinct_markers():
    assert marker("openai/gpt-5.6-luna") != marker("deepseek/deepseek-flash")


def test_scoped_marker_does_not_contain_legacy_marker():
    # The delete filter matches on substrings. If a scoped marker contained the
    # legacy one, every job's legacy sweep would delete every other job's fresh
    # comments -- the exact bug this change fixes.
    for key in ("openai/gpt-5.6-luna", "deepseek/deepseek-flash", "gpt-4o"):
        assert LEGACY not in marker(key)


def scope_of(m: str) -> str:
    """The key portion, between the `:` and the closing delimiter."""
    return m.removeprefix("<!-- aider-code-review:").removesuffix(" -->")


def test_double_hyphen_is_collapsed():
    # "--" terminates an HTML comment early, so a key carrying one would close
    # the marker at the wrong place and leak the rest as visible text. (The
    # `<!--`/`-->` delimiters legitimately contain "--"; only the key is checked.)
    assert "--" not in scope_of(marker("vendor/model--weird"))
    assert scope_of(marker("vendor/model--weird")) == "vendor/model-weird"


def test_angle_brackets_are_stripped():
    assert marker("a>b") == "<!-- aider-code-review:a-b -->"
    assert marker("<script>") == "<!-- aider-code-review:-script- -->"


def test_empty_key_falls_back_to_a_scope_not_the_legacy_marker():
    assert marker("") != LEGACY
    assert LEGACY not in marker("")
