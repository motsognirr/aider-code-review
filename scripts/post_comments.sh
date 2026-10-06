#!/usr/bin/env bash
# Post fresh inline + summary comments, then delete this reviewer's prior ones.
# Required env: REPO, PR_NUMBER, SANDBOX
# Optional env: DRY_RUN (true|false, default false)
#               MODEL, COMMENT_KEY  -- scope the marker (see comment_marker.py)
#               SWEEP_LEGACY_COMMENTS (true|false, default true)
set -euo pipefail

: "${REPO:?REPO is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${SANDBOX:?SANDBOX is required}"
: "${DRY_RUN:=false}"
: "${MODEL:=}"
: "${COMMENT_KEY:=}"
: "${SWEEP_LEGACY_COMMENTS:=true}"

SCRIPT_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)

# One comment namespace per reviewer. Concurrent jobs reviewing the same PR
# with different models must not match each other's comments -- a shared marker
# meant whichever job finished last deleted the other's findings.
LEGACY_MARKER="<!-- aider-code-review -->"
MARKER=$("$SCRIPT_DIR/comment_marker.py" "${COMMENT_KEY:-$MODEL}")
echo "Comment marker: $MARKER"

FINDINGS_FILE="$SANDBOX/findings.json"
SUMMARY_FILE="$SANDBOX/summary.md"
HEAD_SHA=$(cat "$SANDBOX/head_sha")

if [ "$DRY_RUN" = "true" ]; then
  echo "DRY RUN — would post the following:"
  echo "--- inline findings ---"
  jq . "$FINDINGS_FILE"
  echo "--- summary ---"
  cat "$SUMMARY_FILE"
  jq -r 'length' "$FINDINGS_FILE" > "$SANDBOX/posted_inline_count"
  echo "0" > "$SANDBOX/failed_posts_count"
  echo "" > "$SANDBOX/summary_url"
  exit 0
fi

# Post first, delete after. Deleting up front meant any posting failure left
# the PR with no review at all; this way it keeps the previous one. The stale
# set is captured *before* posting, since fresh comments carry the same marker.
list_stale() {
  gh api --paginate "$1" \
    | jq -r --arg marker "$MARKER" \
        --arg legacy_marker "$LEGACY_MARKER" \
        --argjson sweep_legacy "$SWEEP_LEGACY_COMMENTS" \
        -f "$SCRIPT_DIR/select_stale_comments.jq"
}
echo "Listing prior comments for this marker..."
list_stale "repos/$REPO/pulls/$PR_NUMBER/comments" > "$SANDBOX/stale_inline_ids"
list_stale "repos/$REPO/issues/$PR_NUMBER/comments" > "$SANDBOX/stale_issue_ids"

posted=0
failed=0
finding_count=$(jq -r 'length' "$FINDINGS_FILE")
echo "Posting $finding_count inline comments..."
# Bash arithmetic rather than `seq 0 $((finding_count - 1))`: for an empty
# findings list that asks for `seq 0 -1`, which GNU seq leaves empty but BSD
# seq counts *down* from, posting bogus comments on a macOS runner.
for ((i = 0; i < finding_count; i++)); do
  # A finding jq can't render is a failed post: under `set -e` it would
  # otherwise abort the run after the prior comments were already deleted.
  if ! payload=$(jq -c --arg sha "$HEAD_SHA" --arg marker "$MARKER" --argjson i "$i" '
    .[$i] as $f
    | {
        commit_id: $sha,
        path: $f.path,
        side: "RIGHT",
        line: $f.line,
        body: ($marker + "\n**[" + $f.severity + "/" + $f.category + "]** " + $f.body)
      }
    | if ($f.end_line // null) != null and $f.end_line > $f.line
      then . + {start_line: $f.line, line: $f.end_line, start_side: "RIGHT"}
      else .
      end
  ' "$FINDINGS_FILE" 2>"$SANDBOX/post_err.$i"); then
    failed=$((failed + 1))
    echo "warn: could not build payload for finding $i:" >&2
    cat "$SANDBOX/post_err.$i" >&2
    continue
  fi
  if echo "$payload" | gh api -X POST "repos/$REPO/pulls/$PR_NUMBER/comments" \
       --input - >/dev/null 2>"$SANDBOX/post_err.$i"; then
    posted=$((posted + 1))
  else
    failed=$((failed + 1))
    echo "warn: failed to post finding $i:" >&2
    cat "$SANDBOX/post_err.$i" >&2
  fi
done

echo "Posting summary comment..."
body=$(printf '%s\n## aider-code-review\n\n### Summary\n\n%s\n' "$MARKER" "$(cat "$SUMMARY_FILE")")
if ! summary_url=$(jq -nc --arg body "$body" '{body: $body}' \
     | gh api -X POST "repos/$REPO/issues/$PR_NUMBER/comments" --input - \
     | jq -r '.html_url'); then
  echo "::error::failed to post the summary comment; leaving the previous review in place." >&2
  exit 1
fi

# Delete by snapshot id. `pulls/comments/<id>` and `issues/comments/<id>` are
# the inline and summary delete endpoints respectively.
delete_stale() {
  local kind=$1 ids=$2 cid
  while IFS= read -r cid; do
    [ -z "$cid" ] && continue
    gh api -X DELETE "repos/$REPO/$kind/comments/$cid" >/dev/null || \
      echo "warn: could not delete $kind comment $cid" >&2
  done < "$ids"
}
echo "Deleting prior comments for this marker..."
delete_stale pulls "$SANDBOX/stale_inline_ids"
delete_stale issues "$SANDBOX/stale_issue_ids"

echo "$posted" > "$SANDBOX/posted_inline_count"
echo "$failed" > "$SANDBOX/failed_posts_count"
echo "$summary_url" > "$SANDBOX/summary_url"
echo "Done. Posted $posted inline, $failed failed. Summary: $summary_url"
