import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "resolve_provider.py"


def run(model):
    return subprocess.run(
        [sys.executable, str(SCRIPT), model],
        capture_output=True,
        text=True,
    )


@pytest.mark.parametrize(
    "model",
    ["gpt-4o", "gpt-4.1", "gpt-4o-mini", "o1", "o3-mini", "o4-mini", "openai/gpt-4o"],
)
def test_openai_models_route_to_openai_key(model):
    result = run(model)
    assert result.returncode == 0
    assert result.stdout.strip() == "OPENAI_API_KEY"


@pytest.mark.parametrize(
    "model",
    ["deepseek/deepseek-reasoner", "deepseek/deepseek-chat", "some-other-model"],
)
def test_other_models_route_to_deepseek_key(model):
    result = run(model)
    assert result.returncode == 0
    assert result.stdout.strip() == "DEEPSEEK_API_KEY"


def test_empty_model_falls_back_to_deepseek():
    # No model string should never happen in practice (the action always
    # supplies one), but the resolver treats it as the DeepSeek fallback
    # rather than erroring.
    result = run("")
    assert result.returncode == 0
    assert result.stdout.strip() == "DEEPSEEK_API_KEY"
