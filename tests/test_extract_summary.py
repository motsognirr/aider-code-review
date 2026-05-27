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
