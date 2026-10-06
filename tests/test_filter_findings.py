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


def _at(path, line):
    return {"path": path, "line": line, "severity": "low",
            "category": "bug", "body": "x"}


def test_added_lines_that_look_like_file_headers_still_count(tmp_path):
    # `+++i;` is the added line `++i;` and `--- removed...` is the removed line
    # `-- removed...`; inside a hunk neither is a file header. Line 2 is `++i;`,
    # line 3 the header lookalike, line 4 `check(i);`.
    findings = [_at("src/loop.c", 2), _at("src/loop.c", 3), _at("src/loop.c", 4)]
    result = run(findings, "diff_marker_lookalikes.diff", tmp_path)
    assert result.returncode == 0
    assert json.loads(result.stdout) == findings


def test_header_lookalike_does_not_hijack_the_file_path(tmp_path):
    findings = [_at("not/a/header.c", 1), _at("src/next.c", 4)]
    result = run(findings, "diff_marker_lookalikes.diff", tmp_path)
    assert json.loads(result.stdout) == [_at("src/next.c", 4)]


def test_context_line_after_lookalikes_is_still_dropped(tmp_path):
    # `return i;` is new-side line 5, a context line.
    result = run([_at("src/loop.c", 5)], "diff_marker_lookalikes.diff", tmp_path)
    assert json.loads(result.stdout) == []


def test_drops_findings_whose_text_fields_are_not_strings(tmp_path):
    # post_comments.sh concatenates severity/category/body into the comment;
    # a number there is a jq type error, not a comment.
    good = {"path": "src/foo.py", "line": 12, "severity": "high",
            "category": "bug", "body": "real"}
    bad = [
        {**good, "severity": 3},
        {**good, "category": ["bug"]},
        {**good, "body": None},
        {**good, "body": "   "},
    ]
    result = run([good, *bad], "diff_basic.diff", tmp_path)
    assert json.loads(result.stdout) == [good]


def test_diff_fixtures_are_well_formed_patches():
    # A hand-written fixture with a miscounted hunk header can make a test pass
    # for the wrong reason, since the parser trusts those counts.
    for fixture in sorted(FIX.glob("*.diff")):
        proc = subprocess.run(["git", "apply", "--stat", str(fixture)],
                              capture_output=True, text=True)
        assert proc.returncode == 0, f"{fixture.name}: {proc.stderr}"
