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


def test_reasoning_section_heading_is_not_the_summary():
    # A reasoning model's THINKING section can contain a `## Summary` line of
    # its own (here: musing about the output format). Only the ANSWER counts.
    result = run("aider_stdout_reasoning_with_summary.txt")
    assert result.returncode == 0
    assert result.stdout == (
        "Clean hardening: pins the review action by SHA and caps both reviewer jobs.\n"
    )


def test_reasoning_only_summary_counts_as_missing():
    # Better the "no summary" fallback than posting the model's musings.
    result = run("aider_stdout_reasoning_no_summary.txt")
    assert result.returncode == 2


def test_usage_report_is_not_part_of_the_summary():
    result = run("aider_stdout_with_summary_and_usage.txt")
    assert result.returncode == 0
    assert result.stdout == "All good.\n"


def test_two_line_usage_report_is_stripped_but_prose_about_tokens_kept():
    # With cache hits and writes aider puts `Cost:` on its own line. A summary
    # sentence that merely mentions tokens is content, not the report.
    result = run("aider_stdout_summary_two_line_usage.txt")
    assert result.returncode == 0
    assert result.stdout == "Nothing blocking. Token budgets are respected by the new limiter.\n"


def test_last_summary_heading_wins():
    # Same rule as extract_json's last block: an earlier heading is a draft.
    result = run("aider_stdout_two_summaries.txt")
    assert result.returncode == 0
    assert result.stdout == "final summary\n"
