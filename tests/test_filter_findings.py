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
