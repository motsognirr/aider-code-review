# aider-code-review — v1 design

Status: approved 2026-05-27
Issue: [motsognirr/olmlx#385](https://github.com/motsognirr/olmlx/issues/385)

## Goal

A reusable GitHub Action, `motsognirr/aider-code-review@v1`, that performs
agentic PR review using [aider](https://aider.chat) with DeepSeek as the
backend model. Distributed as a composite action; consumed from many repos
with a ≤20-line caller workflow. Replaces the per-repo
`anthropics/claude-code-action@v1`-based reviewer.

## Non-goals (this version)

- Benchmarking against historical Claude reviews on five olmlx PRs.
- Swapping `motsognirr/olmlx/.github/workflows/claude-code-review.yml`.
- Supporting `ubuntu-latest` or any non-macOS runner — v1 targets the
  user's self-hosted macOS runners only. Portability can come later.
- The `@claude` mention bot in olmlx's `claude.yml`.

## Architecture

### Distribution

Composite GitHub Action at the root of `motsognirr/aider-code-review`.
Consumed as:

```yaml
- uses: motsognirr/aider-code-review@v1
  with:
    deepseek_api_key: ${{ secrets.DEEPSEEK_API_KEY }}
    github_token: ${{ secrets.GITHUB_TOKEN }}
```

Released with semver tags (`v1.0.0`, `v1.1.0`, …) plus a moving `v1`
alias updated on every minor release. SHA-pinning is supported.

### Repo layout

```
action.yml                       # composite action manifest
scripts/
  run-review.sh                  # main orchestrator
  fetch-pr-context.sh            # gh api → diff + base/head file blobs
  filter-findings.sh             # hallucination guard
  post-comments.sh               # inline + summary posting
  extract-json.sh                # parse fenced JSON from aider stdout
prompts/
  architect.md                   # planning prompt
  editor.md                      # structured-output review prompt
tests/
  fixtures/                      # sample diffs + findings JSON
  filter-findings.bats           # hallucination-guard unit tests
  extract-json.bats              # JSON extraction edge cases
  parse-summary.bats             # ## Summary extraction
README.md
.github/workflows/
  ci.yml                         # bats tests on push
  self-test.yml                  # dry-run review on this repo's own PRs
  release.yml                    # tag v1 alias on minor release
```

### Caller workflow contract

```yaml
name: PR review
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

Total: 14 lines.

### Runner prerequisites

Self-hosted macOS runners must have:

```bash
brew install gh jq python@3.12
```

aider itself is installed by the action at runtime via
`pip install --user aider-chat==<pinned>` (pin chosen at release time).
Install happens before any PR data lands on disk.

## Fork-safety model

The action is invoked from `pull_request_target`, which runs in the base
repo's context with access to secrets. The action enforces these
invariants to keep PR-author-controlled content from ever executing:

1. **No PR-head checkout into an executable working tree.** The action
   does not run `actions/checkout` of the PR head. It does its own
   `actions/checkout` of the base SHA into a sandboxed
   `$RUNNER_TEMP/aider-review-<run_id>` directory and never touches the
   caller's `$GITHUB_WORKSPACE`. The README explicitly warns callers
   against checking out the PR head themselves.
2. **No PR-code execution.** No `pip install -r`, `npm install`, build
   hooks, or test runs against PR content. aider is installed from PyPI
   before any PR data is fetched.
3. **PR files as data only.** Changed file contents are fetched via
   `gh api /repos/{owner}/{repo}/contents/{path}?ref={pr_head_sha}`,
   written to `$SANDBOX/head/` and `$SANDBOX/base/`, and passed to aider
   via `--read` (read-only mounts). aider runs with `--no-auto-commits
   --no-git --yes-always` so it cannot write back or invoke shell.
4. **No PR strings interpreted as commands.** All `gh api` calls use
   `--jq` for parsing. All shell variables holding PR-derived strings
   (paths, titles, bodies) are double-quoted. No `eval`.
5. **First-time contributor gate** (optional). Input
   `first_time_contributor_gate_label`, e.g. `safe-to-review`: when set,
   the action exits cleanly without reviewing if
   `pull_request.author_association` is `FIRST_TIME_CONTRIBUTOR`,
   `FIRST_TIMER`, or `NONE` AND the PR does not carry that label. A
   maintainer applies the label to opt the PR in.
6. **Secret scrubbing.** Before posting the summary comment, the action
   redacts any occurrence of `$DEEPSEEK_API_KEY` or `$GITHUB_TOKEN` from
   aider's stdout (defense in depth against the model echoing them).

README documents this model under "Fork-safety" with an explicit
"Do NOT do this in your caller workflow" anti-pattern list.

## Review pipeline

### Stage 0 — Setup

In `$SANDBOX = $RUNNER_TEMP/aider-review-$GITHUB_RUN_ID`:

- `git init` an empty repo (avoids aider warnings; `--no-git` disables
  commit/tracking behavior).
- Fetch PR diff: `gh pr diff $PR --repo $REPO --patch > pr.diff`.
- Fetch PR metadata via `gh api`: title, body, `author_association`,
  `head.sha`, `base.sha`, `changed_files` list.
- For each changed file (capped at `max_files`, default 20):
  - Skip if path matches any `exclude_patterns` glob. Defaults:
    `**/*.lock`, `**/dist/**`, `**/node_modules/**`, `**/*.min.*`,
    `**/generated/**`, `**/*.svg`, `**/*.png`, `**/*.jpg`.
  - Fetch base version via
    `gh api /repos/$REPO/contents/$path?ref=$base_sha` → `base/$path`.
    Tolerate 404 (new file).
  - Fetch head version via
    `gh api /repos/$REPO/contents/$path?ref=$head_sha` → `head/$path`.
    Tolerate 404 (deleted file).
- If `total_changed_files > max_files`, record `skipped_files = N` for
  inclusion in the final summary.

### Stage 1 — Architect (planner + editor)

```bash
aider --architect \
  --model deepseek/deepseek-reasoner \
  --editor-model deepseek/deepseek-chat \
  --no-auto-commits --no-git --yes-always --no-stream \
  --no-show-model-warnings --no-check-update \
  --read pr.diff \
  --read head/<file1> --read head/<file2> ... \
  --message "$(cat prompts/architect.md)" \
  > aider.stdout 2> aider.stderr
```

`prompts/architect.md` instructs the model to:

- Identify the 3–10 highest-risk findings in the diff.
- Restrict categories to bug / logic / security / perf / maintainability;
  skip nits and style.
- Reference exact `path` + `line` from the diff, where `line` is the
  line number in the new (head) version of the file.
- Emit findings as a single fenced ```json``` block matching:
  ```json
  [
    {
      "path": "src/foo.py",
      "line": 42,
      "end_line": 47,
      "severity": "high|medium|low",
      "category": "bug|security|perf|maintainability",
      "body": "markdown comment text"
    }
  ]
  ```
- Follow the JSON block with a short freeform `## Summary` section
  intended for the top-level issue comment.

### Stage 2 — Parse & validate

`scripts/extract-json.sh`:
- Extract the last fenced ```json``` block from `aider.stdout`.
- Parse with `jq`. On parse failure, emit a sentinel that the caller
  treats as "unstructured output" (see Error handling).

`scripts/filter-findings.sh` — the hallucination guard:
- For each finding, verify:
  - `path` appears in the PR's `changed_files` list.
  - `line` falls within an added-or-modified hunk of `path` in
    `pr.diff` (parsed by walking `@@ -a,b +c,d @@` headers).
  - If `end_line` is present, it is ≥ `line` and also within the same
    file's added-or-modified region.
- Drop findings that fail any check; increment `dropped_hallucinations`.

`scripts/extract-json.sh` (continued):
- Extract the `## Summary` section text. If absent, synthesize:
  `Reviewed N files, surfaced K findings (H high, M medium, L low).`

### Stage 3 — Post

`scripts/post-comments.sh`:
- **Idempotency first.** Fetch existing inline + issue comments
  authored by `github-actions[bot]` whose bodies contain the marker
  `<!-- aider-code-review -->`. Delete them. This handles re-runs on
  `synchronize` without accumulating duplicate noise.
- **Inline comments.** For each surviving finding:
  ```
  POST /repos/$REPO/pulls/$PR/comments
  {
    "commit_id": "$head_sha",
    "path": "<finding.path>",
    "side": "RIGHT",
    "line": <finding.line>,
    "start_line": <finding.line if end_line else absent>,
    "body": "<!-- aider-code-review -->\n**[severity/category]** <body>"
  }
  ```
  On per-finding POST failure: log, increment `failed_posts`, continue.
- **Summary comment.**
  ```
  POST /repos/$REPO/issues/$PR/comments
  body: "<!-- aider-code-review -->\n## aider-code-review\n<summary>"
  ```
  Appends a "Skipped N files (max_files cap)" line if applicable; a
  "⚠️ Failed to post K inline comments" line if applicable.

## Inputs / outputs

### Inputs

| Input | Required | Default | Notes |
|---|---|---|---|
| `deepseek_api_key` | yes | — | Passed to aider as `DEEPSEEK_API_KEY` |
| `github_token` | yes | — | For `gh api`; needs `pull-requests: write`, `contents: read` |
| `pr_number` | no | `${{ github.event.pull_request.number }}` | Override for `workflow_dispatch` |
| `repo` | no | `${{ github.repository }}` | Override for cross-repo callers |
| `model` | no | `deepseek/deepseek-reasoner` | aider architect model |
| `editor_model` | no | `deepseek/deepseek-chat` | aider editor model |
| `max_files` | no | `20` | Cap on fetched changed files |
| `exclude_patterns` | no | (defaults above) | Newline-separated globs |
| `first_time_contributor_gate_label` | no | `""` | If set, gates review on label |
| `aider_version` | no | pinned at release | e.g. `0.86.1` |
| `dry_run` | no | `false` | Print findings to job log; skip posting |

### Outputs

| Output | Description |
|---|---|
| `findings_count` | Surviving findings posted (or would-be-posted in dry_run) |
| `dropped_hallucinations_count` | Findings dropped by the guard |
| `summary_comment_url` | URL of the posted summary comment |
| `posted_inline_count` | Inline comments successfully posted |
| `failed_posts_count` | Inline POSTs that errored |

## Error handling

| Condition | Behavior |
|---|---|
| Missing `deepseek_api_key` or `github_token` | Fail step before any network call with a clear message |
| `gh api` fetch failure (diff or files) | Fail step; log line names the failing endpoint and HTTP status |
| First-time-contributor gate triggers | Exit 0 cleanly; no review posted; job summary notes the skip |
| aider non-zero exit | Capture stderr to `$RUNNER_TEMP/aider.log`; still attempt to parse stdout for partial JSON; post summary with `⚠️ Review incomplete` and stderr tail in `<details>` |
| JSON parse failure | Post summary `⚠️ Model produced unstructured output` with raw stdout in `<details>` (after secret scrubbing) |
| Inline-comment POST failure | Log, increment `failed_posts_count`, continue with next finding |
| Zero surviving findings | Post `✅ aider-code-review found no high-signal issues.` summary |
| `dry_run: true` | Print findings table to job log; do not POST |

## Testing

- `tests/filter-findings.bats` — hallucination-guard unit tests
  (bats-core). Fixtures cover: line in added hunk (keep), line in
  deleted hunk (drop), file not in PR (drop), line outside any hunk
  (drop), `end_line < line` (drop), valid multi-line range (keep).
- `tests/extract-json.bats` — JSON-block extraction edge cases:
  multiple fenced blocks (last wins), no fenced block (empty),
  malformed JSON (error path).
- `tests/parse-summary.bats` — `## Summary` section extraction
  (present, absent, multiple `##` headers).
- `.github/workflows/ci.yml` — `bats tests/` on every push.
- `.github/workflows/self-test.yml` — runs the action against this
  repo's own PRs with `dry_run: true` on self-hosted macOS, so the
  action exercises its full path without spamming itself.

## Open questions

None at design time. Tuning the prompt and `max_files` cap will happen
empirically after first live use.
