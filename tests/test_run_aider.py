"""run_aider.sh against a stubbed `aider` that records its env and argv.

aider reads attacker-controlled PR content and runs with --yes-always, so it
must never be handed the GitHub token, nor be allowed to propose (and thereby
auto-run) shell commands that could exfiltrate whatever it does hold.
"""

import os
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SCRIPT = REPO_ROOT / "scripts" / "run_aider.sh"

AIDER_STUB = r"""#!/usr/bin/env bash
env > "$STUB_ENV_OUT"
printf '%s\n' "$@" > "$STUB_ARGV_OUT"
echo "aider stdout"
"""


@pytest.fixture
def run(tmp_path):
    binp = tmp_path / "bin"
    binp.mkdir()
    stub = binp / "aider"
    stub.write_text(AIDER_STUB)
    stub.chmod(0o755)

    sandbox = tmp_path / "sandbox"
    (sandbox / "head" / "src").mkdir(parents=True)
    (sandbox / "pr.diff").write_text("")
    (sandbox / "head" / "src" / "a.py").write_text("x = 1\n")
    (sandbox / "included_files.txt").write_text("src/a.py\nsrc/missing.py\n")

    env_out = tmp_path / "env.out"
    argv_out = tmp_path / "argv.out"
    env = {
        **os.environ,
        "PATH": f"{binp}:{os.environ['PATH']}",
        "STUB_ENV_OUT": str(env_out),
        "STUB_ARGV_OUT": str(argv_out),
        "SANDBOX": str(sandbox),
        "ACTION_DIR": str(REPO_ROOT),
        "MODEL": "deepseek/deepseek-reasoner",
        "KEY_VAR": "DEEPSEEK_API_KEY",
        "DEEPSEEK_API_KEY": "sk-deepseek",
        "GH_TOKEN": "ghs_secret",
        "GITHUB_TOKEN": "ghs_secret2",
    }
    proc = subprocess.run(["bash", str(SCRIPT)], env=env, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    aider_env = dict(
        line.split("=", 1) for line in env_out.read_text().splitlines() if "=" in line
    )
    return aider_env, argv_out.read_text().splitlines(), sandbox


def test_aider_does_not_receive_github_tokens(run):
    aider_env, _, _ = run
    assert "GH_TOKEN" not in aider_env
    assert "GITHUB_TOKEN" not in aider_env


def test_aider_receives_the_provider_key(run):
    aider_env, _, _ = run
    assert aider_env["DEEPSEEK_API_KEY"] == "sk-deepseek"


def test_aider_shell_command_suggestions_disabled(run):
    _, argv, _ = run
    assert "--no-suggest-shell-commands" in argv


def test_aider_reads_diff_and_fetched_head_files_only(run):
    _, argv, _ = run
    reads = [argv[i + 1] for i, a in enumerate(argv) if a == "--read"]
    assert reads == ["pr.diff", "head/src/a.py"]


def test_aider_stdout_lands_in_sandbox(run):
    _, _, sandbox = run
    assert (sandbox / "aider.stdout").read_text() == "aider stdout\n"
