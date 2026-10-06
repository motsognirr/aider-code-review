#!/usr/bin/env bash
# Run aider over the fetched PR context in $SANDBOX.
# Required env: SANDBOX, ACTION_DIR, MODEL, KEY_VAR (+ the variable it names)
# Optional env: API_TIMEOUT (seconds per model API call, default 600)
# Writes $SANDBOX/aider.stdout and $SANDBOX/aider.stderr; exits with aider's rc.
set -euo pipefail

: "${SANDBOX:?SANDBOX is required}"
: "${ACTION_DIR:?ACTION_DIR is required}"
: "${MODEL:?MODEL is required}"
: "${KEY_VAR:?KEY_VAR is required}"
: "${API_TIMEOUT:=600}"

cd "$SANDBOX"
git init --quiet . >/dev/null

read_args=( --read pr.diff )
while IFS= read -r path; do
  [ -z "$path" ] && continue
  [ -f "head/$path" ] && read_args+=( --read "head/$path" )
done < "$SANDBOX/included_files.txt"

# Ask mode: aider only answers; no editor pass, no SEARCH/REPLACE edits.
# Architect mode would feed our prompt to an editor model that tries to
# turn the response into file edits, which mangles structured JSON output.
#
# COLUMNS: aider renders output through rich, which word-wraps to the console
# width — 80 cols when stdout is not a TTY (as in CI). That wrapping injects
# raw newlines into the model's JSON string values, producing invalid JSON
# (illegal control characters) that the extractor would otherwise reject. A
# wide width keeps the JSON (and finding bodies) unwrapped. --no-pretty alone
# does not disable width-based wrapping.
#
# aider reads attacker-controlled PR content and runs with --yes-always, so a
# prompt injection in the diff must not be able to get a shell command
# auto-run, and there must be no GitHub token in its environment to steal.
#
# --timeout: aider's default is none, so a stalled provider request would
# hang the job until GitHub's 6-hour cap.
exec env -u GH_TOKEN -u GITHUB_TOKEN "$KEY_VAR=${!KEY_VAR}" COLUMNS=2000 aider \
  --chat-mode ask \
  --model "$MODEL" \
  --no-pretty \
  --no-auto-commits --no-git --yes-always --no-stream \
  --no-show-model-warnings --no-check-update \
  --no-suggest-shell-commands \
  --timeout "$API_TIMEOUT" \
  "${read_args[@]}" \
  --message "$(cat "$ACTION_DIR/prompts/architect.md")" \
  > "$SANDBOX/aider.stdout" 2> "$SANDBOX/aider.stderr"
