#!/usr/bin/env bash
# Fetch PR context (diff, metadata, head file blobs) into $SANDBOX.
# Required env: REPO, PR_NUMBER, SANDBOX, MAX_FILES, EXCLUDE_PATTERNS
set -euo pipefail

: "${REPO:?REPO is required}"
: "${PR_NUMBER:?PR_NUMBER is required}"
: "${SANDBOX:?SANDBOX is required}"
: "${MAX_FILES:=20}"
: "${EXCLUDE_PATTERNS:=}"

mkdir -p "$SANDBOX/head"

echo "Fetching PR diff..."
gh pr diff "$PR_NUMBER" --repo "$REPO" --patch > "$SANDBOX/pr.diff"

echo "Fetching PR metadata..."
gh api "repos/$REPO/pulls/$PR_NUMBER" > "$SANDBOX/meta.json"

HEAD_SHA=$(jq -r '.head.sha' < "$SANDBOX/meta.json")
echo "$HEAD_SHA" > "$SANDBOX/head_sha"
jq -r '.base.sha' < "$SANDBOX/meta.json" > "$SANDBOX/base_sha"
jq -r '.author_association' < "$SANDBOX/meta.json" > "$SANDBOX/author_association"

echo "Listing changed files..."
gh api --paginate "repos/$REPO/pulls/$PR_NUMBER/files" \
  | jq -r '.[] | select(.status != "removed") | .filename' \
  > "$SANDBOX/all_changed_files.txt"

# Apply exclude patterns + max_files cap.
> "$SANDBOX/included_files.txt"
included=0
total=0
while IFS= read -r path; do
  total=$((total + 1))
  if [ -n "$EXCLUDE_PATTERNS" ]; then
    excluded=0
    while IFS= read -r pat; do
      [ -z "$pat" ] && continue
      # shellcheck disable=SC2053
      case "$path" in
        $pat) excluded=1; break ;;
      esac
    done <<< "$EXCLUDE_PATTERNS"
    [ "$excluded" -eq 1 ] && continue
  fi
  if [ "$included" -ge "$MAX_FILES" ]; then
    continue
  fi
  printf '%s\n' "$path" >> "$SANDBOX/included_files.txt"
  included=$((included + 1))
done < "$SANDBOX/all_changed_files.txt"

echo "Included $included of $total changed files (max_files=$MAX_FILES)."
echo "$total" > "$SANDBOX/total_changed_files"
echo "$included" > "$SANDBOX/included_files_count"

echo "Fetching head blobs..."
while IFS= read -r path; do
  dest="$SANDBOX/head/$path"
  mkdir -p "$(dirname "$dest")"
  # Tolerate 404 (deleted files were already filtered above, but a race is possible).
  if ! gh api "repos/$REPO/contents/$path?ref=$HEAD_SHA" \
       --jq '.content' 2>/dev/null \
       | base64 --decode > "$dest" 2>/dev/null; then
    echo "warn: failed to fetch head blob for $path; skipping" >&2
    rm -f "$dest"
  fi
done < "$SANDBOX/included_files.txt"

echo "Fetch complete."
