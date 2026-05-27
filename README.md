# aider-code-review

Reusable GitHub Action that performs agentic PR review using
[aider](https://aider.chat) with DeepSeek as the backend model. Posts
inline `path:line` comments and a top-level summary. Fork-safe: PRs from
forks are reviewed without exposing secrets to PR-controlled code.

## Quick start

In any consumer repo, add `.github/workflows/aider-review.yml`:

```yaml
name: aider PR review
on:
  pull_request_target:
    types: [opened, synchronize, reopened]
permissions:
  pull-requests: write
  contents: read
jobs:
  review:
    runs-on: [self-hosted, macOS]
    steps:
      - uses: motsognirr/aider-code-review@v1
        with:
          deepseek_api_key: ${{ secrets.DEEPSEEK_API_KEY }}
          github_token: ${{ secrets.GITHUB_TOKEN }}
```

Set the `DEEPSEEK_API_KEY` secret in the consumer repo (or org).

## Runner prerequisites

Self-hosted macOS runners must have:

```bash
brew install gh jq python@3.12
```

aider is installed by the action at runtime.

## Fork-safety model

The action is designed for `pull_request_target` so that secrets are
available. To prevent attacker-controlled PR code from executing with
those secrets:

- The action does NOT run `actions/checkout` of the PR head.
- It fetches the diff and head file blobs via the GitHub API, into a
  sandboxed `$RUNNER_TEMP/aider-review-<run_id>` directory.
- aider is installed from PyPI before any PR data is fetched.
- aider runs with `--no-auto-commits --no-git --yes-always` and
  read-only file mounts; it cannot write back or shell out.
- All PR-derived strings (paths, titles, bodies) are passed as data,
  never `eval`'d.
- Optional `first_time_contributor_gate_label` requires a maintainer
  to apply the named label before first-time contributors get reviewed.

### Do NOT do this in your caller workflow

```yaml
# BAD: this checks out PR-author code into a tree where secrets exist.
- uses: actions/checkout@v4
  with:
    ref: ${{ github.event.pull_request.head.sha }}
- run: pip install -r requirements.txt  # arbitrary code from PR
- uses: motsognirr/aider-code-review@v1
  with:
    deepseek_api_key: ${{ secrets.DEEPSEEK_API_KEY }}
```

The action does its own sandboxed setup; the caller should add no
checkout, install, or test steps before invoking it.

## Inputs

| Input | Required | Default | Notes |
|---|---|---|---|
| `deepseek_api_key` | yes | — | Passed to aider as `DEEPSEEK_API_KEY` |
| `github_token` | yes | — | Needs `pull-requests: write`, `contents: read` |
| `pr_number` | no | event payload | Override for `workflow_dispatch` |
| `repo` | no | workflow repo | Override for cross-repo callers |
| `model` | no | `deepseek/deepseek-reasoner` | aider architect model |
| `editor_model` | no | `deepseek/deepseek-chat` | aider editor model |
| `max_files` | no | `20` | Cap on fetched changed files |
| `exclude_patterns` | no | sane defaults | Newline-separated globs |
| `first_time_contributor_gate_label` | no | `""` | If set, gates review on label |
| `aider_version` | no | latest | Pin for reproducibility |
| `dry_run` | no | `"false"` | Print findings to job log; skip posting |

## Outputs

| Output | Description |
|---|---|
| `findings_count` | Surviving findings posted (or would-be in dry_run) |
| `dropped_hallucinations_count` | Findings dropped by the guard |
| `posted_inline_count` | Inline comments successfully posted |
| `failed_posts_count` | Inline POSTs that errored |
| `summary_comment_url` | URL of the posted summary comment |

## How it works

1. Sandboxed setup: install aider from PyPI; fetch the PR diff,
   metadata, and head file blobs via `gh api`.
2. Run aider in `--architect` mode against the diff plus the head
   versions of changed files (read-only), with a prompt asking for
   structured JSON findings plus a `## Summary` section.
3. Parse the JSON. Drop any finding whose `path:line` isn't a `+`
   line in the PR diff (hallucination guard).
4. Delete any previous bot comments tagged with the action's marker
   (idempotency on `synchronize`). Post inline comments and a summary.

## Releases

- `v1.x.y` — semver releases.
- `v1` — moving alias updated on every minor/patch release.
- Action is also pinnable by full SHA.

## License

MIT.
