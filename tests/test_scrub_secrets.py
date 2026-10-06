"""scrub_secrets.py redacts credential values from files bound for the PR.

Both aider's stdout and its stderr tail end up in the public summary comment,
so every file passed must be scrubbed, not just the first.
"""

import os
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "scrub_secrets.py"

SECRETS = {
    "DEEPSEEK_API_KEY": "sk-deepseek-123",
    "OPENAI_API_KEY": "sk-openai-456",
    "GH_TOKEN": "ghs_token789",
    "GITHUB_TOKEN": "ghs_other000",
}


def scrub(tmp_path, contents, env_secrets=SECRETS):
    paths = []
    for i, text in enumerate(contents):
        p = tmp_path / f"f{i}.txt"
        p.write_text(text)
        paths.append(p)
    env = {k: v for k, v in os.environ.items() if k not in SECRETS}
    env.update(env_secrets)
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), *map(str, paths)],
        env=env, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return [p.read_text() for p in paths]


def test_every_secret_is_redacted(tmp_path):
    (out,) = scrub(tmp_path, [" ".join(SECRETS.values())])
    assert out == " ".join(["[REDACTED]"] * len(SECRETS))


def test_every_file_is_scrubbed(tmp_path):
    outs = scrub(tmp_path, ["stdout sk-deepseek-123", "stderr: auth ghs_token789 failed"])
    assert outs == ["stdout [REDACTED]", "stderr: auth [REDACTED] failed"]


def test_unset_or_empty_secrets_leave_text_alone(tmp_path):
    (out,) = scrub(tmp_path, ["nothing secret here"], env_secrets={"GH_TOKEN": ""})
    assert out == "nothing secret here"


def test_missing_file_is_skipped(tmp_path):
    # aider.stderr is never created if run_aider.sh fails before its redirect.
    present = tmp_path / "present.txt"
    present.write_text("sk-deepseek-123")
    proc = subprocess.run(
        [sys.executable, str(SCRIPT), str(tmp_path / "absent.txt"), str(present)],
        env={**os.environ, **SECRETS}, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    assert present.read_text() == "[REDACTED]"


def test_a_secret_containing_another_is_fully_redacted(tmp_path):
    # Replacing the shorter value first would split the longer one into
    # `[REDACTED]<rest>`, leaving the rest of it in the public comment.
    overlap = {"DEEPSEEK_API_KEY": "abc", "OPENAI_API_KEY": "abc-def-ghi"}
    (out,) = scrub(tmp_path, ["key: abc-def-ghi"], env_secrets=overlap)
    assert out == "key: [REDACTED]"
