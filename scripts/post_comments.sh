#!/usr/bin/env bash
# Delete prior bot comments and post fresh inline + summary comments.
# Required env: REPO, PR_NUMBER, SANDBOX
# Optional env: DRY_RUN (true|false, default false)
set -euo pipefail

: "${REPO:?REPO is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${SANDBOX:?SANDBOX is required}"
: "${DRY_RUN:=false}"

MARKER="<!-- aider-code-review -->"

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

echo "Deleting prior bot inline comments with marker..."
gh api --paginate "repos/$REPO/pulls/$PR_NUMBER/comments" \
  | jq -r --arg marker "$MARKER" \
      '.[] | select(.user.type == "Bot" and (.body | contains($marker))) | .id' \
  | while IFS= read -r cid; do
      [ -z "$cid" ] && continue
      gh api -X DELETE "repos/$REPO/pulls/comments/$cid" >/dev/null || \
        echo "warn: could not delete inline comment $cid" >&2
    done

echo "Deleting prior bot summary comments with marker..."
gh api --paginate "repos/$REPO/issues/$PR_NUMBER/comments" \
  | jq -r --arg marker "$MARKER" \
      '.[] | select(.user.type == "Bot" and (.body | contains($marker))) | .id' \
  | while IFS= read -r cid; do
      [ -z "$cid" ] && continue
      gh api -X DELETE "repos/$REPO/issues/comments/$cid" >/dev/null || \
        echo "warn: could not delete issue comment $cid" >&2
    done

posted=0
failed=0
finding_count=$(jq -r 'length' "$FINDINGS_FILE")
echo "Posting $finding_count inline comments..."
for i in $(seq 0 $((finding_count - 1))); do
  payload=$(jq -c --arg sha "$HEAD_SHA" --arg marker "$MARKER" --argjson i "$i" '
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
  ' "$FINDINGS_FILE")
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
body=$(printf '%s\n## aider-code-review\n\n%s\n' "$MARKER" "$(cat "$SUMMARY_FILE")")
summary_url=$(jq -nc --arg body "$body" '{body: $body}' \
  | gh api -X POST "repos/$REPO/issues/$PR_NUMBER/comments" --input - \
  | jq -r '.html_url')

echo "$posted" > "$SANDBOX/posted_inline_count"
echo "$failed" > "$SANDBOX/failed_posts_count"
echo "$summary_url" > "$SANDBOX/summary_url"
echo "Done. Posted $posted inline, $failed failed. Summary: $summary_url"
