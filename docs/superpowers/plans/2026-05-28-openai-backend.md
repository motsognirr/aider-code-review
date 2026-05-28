# OpenAI/ChatGPT Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let consumers run the PR review against OpenAI/ChatGPT models (e.g. `gpt-4o`) as an opt-in alternative to the default DeepSeek backend.

**Architecture:** A new Python resolver maps the `model` string to the API-key env var its provider needs (`OPENAI_API_KEY` vs `DEEPSEEK_API_KEY`). `run_review.sh` uses that to validate the right key is present and to export it to aider. `action.yml` gains an `openai_api_key` input and stops hard-requiring `deepseek_api_key`. aider already speaks to OpenAI natively, so the downstream pipeline is untouched.

**Tech Stack:** Bash composite GitHub Action, aider (litellm under the hood), Python 3 + pytest for pure logic.

---

### Task 1: Provider resolver script

Maps a model string to the env-var name carrying its API key. OpenAI when the
name matches `gpt-*`, `o1*`/`o3*`/`o4*`, or `openai/*`; DeepSeek otherwise
(including any unrecognized string, preserving today's fallback behavior).

**Files:**
- Create: `scripts/resolve_provider.py`
- Test: `tests/test_resolve_provider.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_resolve_provider.py`. It mirrors the subprocess style of
`tests/test_extract_json.py` (the resolver is on `sys.path` via
`tests/conftest.py`, but we invoke it as a CLI for parity with the others).

```python
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
    ["deepseek/deepseek-reasoner", "deepseek/deepseek-chat", "some-other-model", ""],
)
def test_other_models_route_to_deepseek_key(model):
    result = run(model)
    assert result.returncode == 0
    assert result.stdout.strip() == "DEEPSEEK_API_KEY"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_resolve_provider.py -v`
Expected: FAIL — `resolve_provider.py` does not exist yet (nonzero return code / no such file).

- [ ] **Step 3: Write minimal implementation**

Create `scripts/resolve_provider.py`:

```python
#!/usr/bin/env python3
"""Resolve a model string to the API-key env var its provider needs.

Usage: resolve_provider.py <model-string>
Stdout: the env var name carrying the key (OPENAI_API_KEY | DEEPSEEK_API_KEY).
Exit codes:
  0 — always. Unrecognized models fall back to DeepSeek, matching prior
      behavior where any non-routed model used the DeepSeek key.
"""
import re
import sys

# Models that route to OpenAI. Matched case-insensitively against the model
# name (the part after any leading "<provider>/").
_OPENAI_NAME = re.compile(r"^(gpt-|o[134])", re.IGNORECASE)


def resolve(model: str) -> str:
    model = model.strip()
    if model.lower().startswith("openai/"):
        return "OPENAI_API_KEY"
    # Strip a leading provider prefix (e.g. "deepseek/") before name match.
    name = model.split("/", 1)[-1] if "/" in model else model
    if _OPENAI_NAME.match(name):
        return "OPENAI_API_KEY"
    return "DEEPSEEK_API_KEY"


def main():
    if len(sys.argv) != 2:
        print("usage: resolve_provider.py <model-string>", file=sys.stderr)
        sys.exit(64)
    print(resolve(sys.argv[1]))


if __name__ == "__main__":
    main()
```

Note on the `o[134]` pattern: it matches `o1*`, `o3*`, `o4*` (current OpenAI
reasoning families) but not `o2`. This is intentional — there is no `o2`
family — and it avoids matching unrelated names that merely start with "o".

- [ ] **Step 4: Make it executable**

Run: `chmod +x scripts/resolve_provider.py`

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_resolve_provider.py -v`
Expected: PASS — all parametrized cases green.

- [ ] **Step 6: Commit**

```bash
git add scripts/resolve_provider.py tests/test_resolve_provider.py
git commit -m "feat: add provider resolver mapping model string to API-key env var"
```

---

### Task 2: action.yml — add openai_api_key input and pass it through

**Files:**
- Modify: `action.yml` (inputs block around line 9-12; env block in the `runs:` step)

- [ ] **Step 1: Make deepseek_api_key optional and add openai_api_key**

In `action.yml`, find the `inputs:` block starting at line 9:

```yaml
inputs:
  deepseek_api_key:
    description: DeepSeek API key (passed to aider as DEEPSEEK_API_KEY).
    required: true
```

Replace it with:

```yaml
inputs:
  deepseek_api_key:
    description: >-
      DeepSeek API key (passed to aider as DEEPSEEK_API_KEY). Required when
      using a DeepSeek model (the default).
    required: false
    default: ""
  openai_api_key:
    description: >-
      OpenAI API key (passed to aider as OPENAI_API_KEY). Required when using
      an OpenAI model (e.g. `model: gpt-4o`).
    required: false
    default: ""
```

- [ ] **Step 2: Pass OPENAI_API_KEY env to the script**

In the `runs:` composite step's `env:` block, find:

```yaml
      env:
        DEEPSEEK_API_KEY: ${{ inputs.deepseek_api_key }}
        GH_TOKEN: ${{ inputs.github_token }}
```

Add the OpenAI key right after the DeepSeek one:

```yaml
      env:
        DEEPSEEK_API_KEY: ${{ inputs.deepseek_api_key }}
        OPENAI_API_KEY: ${{ inputs.openai_api_key }}
        GH_TOKEN: ${{ inputs.github_token }}
```

- [ ] **Step 3: Sanity-check YAML validity**

Run: `python3 -c "import yaml,sys; yaml.safe_load(open('action.yml')); print('ok')"`
Expected: `ok` (if PyYAML is unavailable, skip — the structure is a minimal indentation change).

- [ ] **Step 4: Commit**

```bash
git add action.yml
git commit -m "feat: add openai_api_key input; deepseek_api_key now optional"
```

---

### Task 3: run_review.sh — route, validate, and export the right key

**Files:**
- Modify: `scripts/run_review.sh` (header comment line 4-5; guard line 9; aider call line 103; scrub heredoc line 121)

- [ ] **Step 1: Update the header comment and remove the hard DeepSeek guard**

In `scripts/run_review.sh`, the comment block lines 3-6 reads:

```bash
# Required env vars (set by action.yml):
#   DEEPSEEK_API_KEY, GH_TOKEN, REPO, PR_NUMBER,
#   MODEL, EDITOR_MODEL, MAX_FILES, EXCLUDE_PATTERNS,
#   FIRST_TIME_GATE_LABEL, AIDER_VERSION, DRY_RUN, ACTION_DIR
```

Replace with:

```bash
# Required env vars (set by action.yml):
#   GH_TOKEN, REPO, PR_NUMBER,
#   MODEL, MAX_FILES, EXCLUDE_PATTERNS,
#   FIRST_TIME_GATE_LABEL, AIDER_VERSION, DRY_RUN, ACTION_DIR
# Provider key (exactly one, chosen by MODEL): DEEPSEEK_API_KEY | OPENAI_API_KEY
```

Then delete the hard guard at line 9:

```bash
: "${DEEPSEEK_API_KEY:?DEEPSEEK_API_KEY is required}"
```

(Leave the `GH_TOKEN`, `REPO`, `PR_NUMBER`, `MODEL`, etc. lines that follow it intact.)

- [ ] **Step 2: Resolve and validate the provider key after MODEL is defaulted**

Immediately after the line `: "${ACTION_DIR:?ACTION_DIR is required}"` (line 19,
the last of the `: "${...}"` block) and before `export GH_TOKEN`, insert:

```bash
# --- Resolve which provider key the chosen model needs, and validate it ---
KEY_VAR=$("$ACTION_DIR/scripts/resolve_provider.py" "$MODEL")
case "$KEY_VAR" in
  OPENAI_API_KEY) KEY_INPUT="openai_api_key" ;;
  *)              KEY_INPUT="deepseek_api_key" ;;
esac
if [ -z "${!KEY_VAR:-}" ]; then
  echo "::error::model '$MODEL' requires the '$KEY_INPUT' input (env $KEY_VAR) to be set." >&2
  exit 2
fi
echo "Provider key for model '$MODEL': $KEY_VAR"
```

- [ ] **Step 3: Export the resolved key on the aider invocation**

Find the aider call at line 103:

```bash
DEEPSEEK_API_KEY="$DEEPSEEK_API_KEY" aider \
```

Replace that single line with (indirect expansion passes the right key under
its own name; the unused provider's key is simply never forwarded):

```bash
env "$KEY_VAR=${!KEY_VAR}" aider \
```

- [ ] **Step 4: Scrub the OpenAI key from stdout too**

In the scrub heredoc (line 121), find:

```python
for var in ("DEEPSEEK_API_KEY", "GH_TOKEN"):
```

Replace with:

```python
for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "GH_TOKEN"):
```

- [ ] **Step 5: Lint the script**

Run: `bash -n scripts/run_review.sh && echo "syntax ok"`
Expected: `syntax ok`. If `shellcheck` is installed, also run
`shellcheck scripts/run_review.sh` and confirm no new errors (the `${!KEY_VAR}`
indirect expansion is valid bash and shellcheck-clean).

- [ ] **Step 6: Run the full test suite**

Run: `pytest -q`
Expected: PASS — existing tests plus the new resolver tests. (No shell test
harness exercises `run_review.sh` directly; its routing decision is covered by
the resolver unit tests.)

- [ ] **Step 7: Commit**

```bash
git add scripts/run_review.sh
git commit -m "feat: route aider to OpenAI or DeepSeek key based on model"
```

---

### Task 4: README — document the OpenAI backend

**Files:**
- Modify: `README.md` (Inputs table; new usage subsection)

- [ ] **Step 1: Add openai_api_key to the Inputs table and adjust deepseek row**

In `README.md`, find the Inputs table rows:

```markdown
| Input | Required | Default | Notes |
|---|---|---|---|
| `deepseek_api_key` | yes | — | Passed to aider as `DEEPSEEK_API_KEY` |
| `github_token` | yes | — | Needs `pull-requests: write`, `contents: read` |
```

Replace those two data rows with:

```markdown
| Input | Required | Default | Notes |
|---|---|---|---|
| `deepseek_api_key` | for DeepSeek models | — | Passed to aider as `DEEPSEEK_API_KEY`. Required when `model` is a DeepSeek model (the default). |
| `openai_api_key` | for OpenAI models | — | Passed to aider as `OPENAI_API_KEY`. Required when `model` is an OpenAI model (e.g. `gpt-4o`). |
| `github_token` | yes | — | Needs `pull-requests: write`, `contents: read` |
```

- [ ] **Step 2: Add a "Using OpenAI/ChatGPT" subsection**

Directly after the "## Quick start" section (before "## Runner prerequisites"),
insert:

````markdown
## Using OpenAI/ChatGPT

DeepSeek is the default backend. To review with an OpenAI model instead,
supply `openai_api_key` and set `model` to an OpenAI model (`gpt-*`,
`o1*`/`o3*`/`o4*`, or an explicit `openai/<name>`):

```yaml
      - uses: motsognirr/aider-code-review@v1
        with:
          openai_api_key: ${{ secrets.OPENAI_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
          model: gpt-4o
```

Set the `OPENAI_API_KEY` secret in the consumer repo (or org). You only need
the key that matches your chosen `model`; the action validates this at runtime
and fails fast with a clear error if the matching key is missing.
````

- [ ] **Step 3: Update the `model` row note (optional clarity)**

Find the model row in the Inputs table:

```markdown
| `model` | no | `deepseek/deepseek-reasoner` | Model aider uses in ask mode |
```

Replace with:

```markdown
| `model` | no | `deepseek/deepseek-reasoner` | Model aider uses in ask mode. OpenAI models route to `openai_api_key`; others to `deepseek_api_key`. |
```

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document OpenAI/ChatGPT backend and openai_api_key input"
```

---

## Self-Review Notes

- **Spec coverage:** Inputs (Task 2), resolver + match rule (Task 1), run_review
  routing/validation/scrub (Task 3), README (Task 4), tests (Task 1). All spec
  sections map to a task.
- **Type/name consistency:** `resolve_provider.py` prints exactly
  `OPENAI_API_KEY`/`DEEPSEEK_API_KEY`; `run_review.sh` consumes that string as
  `KEY_VAR` and uses indirect expansion `${!KEY_VAR}`. Env var names match
  across action.yml, run_review.sh, and the scrub list.
- **Fallback behavior preserved:** unrecognized models → `DEEPSEEK_API_KEY`,
  matching the prior implicit behavior.
