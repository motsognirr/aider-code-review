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


def test_control_char_in_body_tolerated():
    # aider word-wraps its output to the console width (80 cols when stdout is
    # not a TTY), injecting raw newlines into JSON string values. Those are
    # illegal control characters under strict JSON, but the findings are
    # otherwise well-formed and recoverable. We must not drop them.
    result = run("aider_stdout_control_char.txt")
    assert result.returncode == 0
    parsed = json.loads(result.stdout)
    assert len(parsed) == 1
    assert parsed[0]["path"] == "olmlx/engine/inference.py"
    # The body survives; the wrap newline is preserved as content.
    assert "generate_transcription" in parsed[0]["body"]
