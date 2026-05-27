import json
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "extract_json.py"
FIX = Path(__file__).resolve().parent / "fixtures"


def run(fixture_name):
    return subprocess.run(
        [sys.executable, str(SCRIPT), str(FIX / fixture_name)],
        capture_output=True,
        text=True,
    )


def test_one_block_emits_array():
    result = run("aider_stdout_one_block.txt")
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert len(parsed) == 1
    assert parsed[0]["path"] == "src/foo.py"


def test_multi_block_uses_last():
    result = run("aider_stdout_multi_block.txt")
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert parsed[0]["path"] == "src/bar.py"


def test_no_block_exits_2():
    result = run("aider_stdout_no_block.txt")
    assert result.returncode == 2
    assert result.stdout.strip() == ""


def test_malformed_exits_3():
    result = run("aider_stdout_malformed.txt")
    assert result.returncode == 3
