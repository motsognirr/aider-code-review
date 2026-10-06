"""Where aider's response starts, when the marker itself gets quoted.

aider writes its reasoning/answer separator exactly once. A model may still
quote it (this repo's own fixtures contain it), so the split must not lose the
real response, and must not let a draft in the thinking win.
"""

import json
import subprocess
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"
FIX = Path(__file__).resolve().parent / "fixtures"


def run(script, fixture):
    return subprocess.run(
        [sys.executable, str(SCRIPTS / script), str(FIX / fixture)],
        capture_output=True, text=True,
    )


def test_marker_quoted_in_the_answer_keeps_the_findings():
    result = run("extract_json.py", "aider_stdout_answer_quotes_marker.txt")
    assert result.returncode == 0, result.stderr
    assert [f["path"] for f in json.loads(result.stdout)] == ["scripts/aider_output.py"]


def test_marker_quoted_in_the_answer_keeps_the_summary():
    result = run("extract_summary.py", "aider_stdout_answer_quotes_marker.txt")
    assert result.returncode == 0
    assert "One low finding." in result.stdout


def test_marker_quoted_in_the_thinking_still_picks_the_real_answer():
    findings = run("extract_json.py", "aider_stdout_thinking_quotes_marker.txt")
    summary = run("extract_summary.py", "aider_stdout_thinking_quotes_marker.txt")
    assert [f["path"] for f in json.loads(findings.stdout)] == ["src/real.py"]
    assert summary.stdout == "real summary\n"


def test_inline_mention_of_the_marker_is_not_the_separator():
    # Only aider's full two-line separator ends the thinking. Splitting on the
    # bare `► **ANSWER**` here would land mid-thinking and post its draft.
    result = run("extract_summary.py", "aider_stdout_thinking_mentions_marker_inline.txt")
    assert result.returncode == 2
