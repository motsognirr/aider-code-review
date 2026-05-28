#!/usr/bin/env bash
# aider-code-review orchestrator. Called by action.yml.
# Required env vars (set by action.yml):
#   GH_TOKEN, REPO, PR_NUMBER,
#   MODEL, MAX_FILES, EXCLUDE_PATTERNS,
#   FIRST_TIME_GATE_LABEL, AIDER_VERSION, DRY_RUN, ACTION_DIR
# Provider key (exactly one, chosen by MODEL): DEEPSEEK_API_KEY | OPENAI_API_KEY
set -euo pipefail

: "${GH_TOKEN:?GH_TOKEN is required}"
: "${REPO:?REPO is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${MODEL:=deepseek/deepseek-reasoner}"
: "${MAX_FILES:=20}"
: "${EXCLUDE_PATTERNS:=}"
: "${FIRST_TIME_GATE_LABEL:=}"
: "${AIDER_VERSION:=}"
: "${DRY_RUN:=false}"
: "${ACTION_DIR:?ACTION_DIR is required}"

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

# Drop the non-selected provider's key from the environment so only the
# resolved key reaches the aider subprocess.
case "$KEY_VAR" in
  OPENAI_API_KEY)   unset DEEPSEEK_API_KEY ;;
  DEEPSEEK_API_KEY) unset OPENAI_API_KEY ;;
esac

export GH_TOKEN

SANDBOX="${RUNNER_TEMP:-/tmp}/aider-review-${GITHUB_RUN_ID:-local}"
export SANDBOX
rm -rf "$SANDBOX"
mkdir -p "$SANDBOX"
echo "Sandbox: $SANDBOX"

# --- Install aider (from PyPI, before any PR data lands on disk) ---
# Use an isolated venv inside the sandbox so we (a) don't rely on a bare
# `pip` being on PATH (brew's python@3.12 only ships pip3) and (b) avoid
# PEP 668 "externally-managed-environment" errors when the runner's
# Python is a brew install.
#
# aider-chat declares `requires_python = ">=3.10,<3.13"`, so we must
# build the venv with a Python in that range. Probe known interpreters
# in preference order and fall back to `python3` only if it qualifies.
PYTHON=""
for candidate in python3.12 python3.11 python3.10 python3; do
  command -v "$candidate" >/dev/null 2>&1 || continue
  pyver=$("$candidate" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null) || continue
  case "$pyver" in
    3.10|3.11|3.12) PYTHON="$candidate"; break ;;
  esac
done
if [ -z "$PYTHON" ]; then
  echo "::error::No compatible Python found. aider-chat requires >=3.10,<3.13;" \
       "install python@3.12 (e.g. \`brew install python@3.12\`) on the runner." >&2
  exit 2
fi
echo "Using $PYTHON ($("$PYTHON" --version)) for aider venv"

VENV="$SANDBOX/venv"
"$PYTHON" -m venv "$VENV"
# Python 3.12+ venvs ship only pip; bootstrap setuptools+wheel so any sdist
# that uses setuptools.build_meta as its PEP 517 backend builds. Prefer
# binary wheels to skip sdist builds entirely when one is available.
"$VENV/bin/pip" install --upgrade pip setuptools wheel
pip_args=( install --prefer-binary )
if [ -n "$AIDER_VERSION" ]; then
  "$VENV/bin/pip" "${pip_args[@]}" "aider-chat==$AIDER_VERSION"
else
  "$VENV/bin/pip" "${pip_args[@]}" "aider-chat"
fi
export PATH="$VENV/bin:$PATH"
aider --version

# --- Fetch PR context ---
SANDBOX="$SANDBOX" REPO="$REPO" PR_NUMBER="$PR_NUMBER" \
  MAX_FILES="$MAX_FILES" EXCLUDE_PATTERNS="$EXCLUDE_PATTERNS" \
  "$ACTION_DIR/scripts/fetch_pr_context.sh"

# --- First-time contributor gate ---
if [ -n "$FIRST_TIME_GATE_LABEL" ]; then
  assoc=$(cat "$SANDBOX/author_association")
  case "$assoc" in
    FIRST_TIME_CONTRIBUTOR|FIRST_TIMER|NONE)
      has_label=$(gh api "repos/$REPO/issues/$PR_NUMBER/labels" \
        --jq "any(.name == \"$FIRST_TIME_GATE_LABEL\")")
      if [ "$has_label" != "true" ]; then
        echo "First-time contributor gate: author_association=$assoc and label '$FIRST_TIME_GATE_LABEL' not present. Skipping review."
        echo "skipped=true" >> "${GITHUB_OUTPUT:-/dev/null}"
        exit 0
      fi
      ;;
  esac
fi

# --- Run aider ---
cd "$SANDBOX"
git init --quiet . >/dev/null

read_args=( --read pr.diff )
while IFS= read -r path; do
  [ -z "$path" ] && continue
  [ -f "head/$path" ] && read_args+=( --read "head/$path" )
done < "$SANDBOX/included_files.txt"

set +e
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
env "$KEY_VAR=${!KEY_VAR}" COLUMNS=2000 aider \
  --chat-mode ask \
  --model "$MODEL" \
  --no-pretty \
  --no-auto-commits --no-git --yes-always --no-stream \
  --no-show-model-warnings --no-check-update \
  "${read_args[@]}" \
  --message "$(cat "$ACTION_DIR/prompts/architect.md")" \
  > "$SANDBOX/aider.stdout" 2> "$SANDBOX/aider.stderr"
aider_rc=$?
set -e
echo "aider exit code: $aider_rc"

# --- Scrub secrets from aider stdout before any further processing ---
python3 - <<PY
import os, re
path = os.environ["SANDBOX"] + "/aider.stdout"
text = open(path, encoding="utf-8", errors="replace").read()
for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "GH_TOKEN"):
    val = os.environ.get(var, "")
    if val:
        text = text.replace(val, "[REDACTED]")
open(path, "w", encoding="utf-8").write(text)
PY

# --- Extract JSON findings ---
findings_json="$SANDBOX/findings_raw.json"
if "$ACTION_DIR/scripts/extract_json.py" "$SANDBOX/aider.stdout" > "$findings_json"; then
  extract_status=ok
else
  rc=$?
  extract_status=fail
  echo "extract_json exit: $rc" >&2
  echo "[]" > "$findings_json"
fi

# --- Filter findings (hallucination guard) ---
"$ACTION_DIR/scripts/filter_findings.py" \
  "$findings_json" "$SANDBOX/pr.diff" \
  > "$SANDBOX/findings.json" 2> "$SANDBOX/filter.err"
dropped=$(grep -oE 'dropped [0-9]+' "$SANDBOX/filter.err" | awk '{print $2}')
dropped="${dropped:-0}"
final_count=$(jq -r 'length' "$SANDBOX/findings.json")
echo "findings: $final_count surviving, $dropped dropped"

# --- Extract summary ---
if "$ACTION_DIR/scripts/extract_summary.py" "$SANDBOX/aider.stdout" \
     > "$SANDBOX/summary.md" 2>/dev/null; then
  :
else
  total=$(cat "$SANDBOX/total_changed_files")
  included=$(cat "$SANDBOX/included_files_count")
  if [ "$final_count" -eq 0 ]; then
    echo "Reviewed $included of $total changed files. No high-signal issues found." > "$SANDBOX/summary.md"
  else
    echo "Reviewed $included of $total changed files. Surfaced $final_count finding(s)." > "$SANDBOX/summary.md"
  fi
fi

# Append warning if aider failed.
if [ "$aider_rc" -ne 0 ]; then
  {
    echo
    echo "⚠️ Review incomplete (aider exit $aider_rc)."
    echo
    echo "<details><summary>aider stderr (tail)</summary>"
    echo
    echo '```'
    tail -n 50 "$SANDBOX/aider.stderr"
    echo '```'
    echo
    echo "</details>"
  } >> "$SANDBOX/summary.md"
fi

# Append warning if JSON parse failed.
if [ "$extract_status" = "fail" ]; then
  {
    echo
    echo "⚠️ Model produced unstructured output."
    echo
    echo "<details><summary>raw aider output (tail)</summary>"
    echo
    echo '```'
    tail -n 80 "$SANDBOX/aider.stdout"
    echo '```'
    echo
    echo "</details>"
  } >> "$SANDBOX/summary.md"
fi

# Append "skipped files" note if applicable.
total=$(cat "$SANDBOX/total_changed_files")
included=$(cat "$SANDBOX/included_files_count")
if [ "$total" -gt "$included" ]; then
  skipped=$((total - included))
  echo "" >> "$SANDBOX/summary.md"
  echo "Note: $skipped file(s) skipped (max_files=$MAX_FILES)." >> "$SANDBOX/summary.md"
fi

# --- Post comments ---
SANDBOX="$SANDBOX" REPO="$REPO" PR_NUMBER="$PR_NUMBER" DRY_RUN="$DRY_RUN" \
  "$ACTION_DIR/scripts/post_comments.sh"

# --- Set action outputs ---
posted=$(cat "$SANDBOX/posted_inline_count")
failed=$(cat "$SANDBOX/failed_posts_count")
summary_url=$(cat "$SANDBOX/summary_url")
{
  echo "findings_count=$final_count"
  echo "dropped_hallucinations_count=$dropped"
  echo "posted_inline_count=$posted"
  echo "failed_posts_count=$failed"
  echo "summary_comment_url=$summary_url"
} >> "${GITHUB_OUTPUT:-/dev/stdout}"
