#!/bin/bash
# loop-context.sh — Priority-Based Backlog Selection for agentic-trading-desk
# Mirrors Adverts-Project pattern: Tier 1 = review-fix items on open PR branches (Rank 0),
# Tier 2 = ranked feature items sorted by rank then filename.

export PATH="$HOME/.local/bin:$PATH"
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../../" && pwd)"
BACKLOG_DIR="$REPO_DIR/backlog"
CIRCLE_BRANCH="autonomous/scaffolding"

# Fetch latest origin state
cd "$REPO_DIR"
git fetch origin --quiet 2>/dev/null || true

# --- Tier 1: Open Branch Priority Feed ---
OPEN_BRANCHES=$(gh pr list --repo seleron/agentic-trading-desk --state open --json number,title,headRefName --jq '.[] | "\(.number) \(.title)"' 2>/dev/null || true)

PRIORITY_FILE=$(mktemp)
trap "rm -f $PRIORITY_FILE" EXIT

if [ -n "$OPEN_BRANCHES" ]; then
    for pr_line in $OPEN_BRANCHES; do
        pr_num=$(echo "$pr_line" | awk '{print $1}')
        # Check if a fix file exists for this PR — try local first, then origin/main
        fix_file=""
        fix_local="$BACKLOG_DIR/$(ls "$BACKLOG_DIR"/ 2>/dev/null | grep "fix-pr${pr_num}" || true)"
        [ -n "$fix_local" ] && [ -f "$fix_local" ] && fix_file="$fix_local"
        # Also check origin/main (where pr-review.sh files fix items)
        if [ -z "$fix_file" ]; then
            fix_remote=$(git ls-tree --name-only -r "origin/main" 2>/dev/null | grep "backlog/.*fix-pr${pr_num}" || true)
            if [ -n "$fix_remote" ] && git cat-file -e "origin/main:$fix_remote" 2>/dev/null; then
                fix_file="$BACKLOG_DIR/$(basename $fix_remote)"
                # Copy it locally so the implementer can read it
                git show "origin/main:$fix_remote" > "$fix_file" 2>/dev/null || true
            fi
        fi
        if [ -n "$fix_file" ] && [ -f "$fix_file" ]; then
             # Skip resolved/completed fix items (check multiple status patterns)
            if grep -q "✅.*RESOLVED" "$fix_file" 2>/dev/null || \
               grep -qiE "✅.*(COMPLETE|RESOLVED)" "$fix_file" 2>/dev/null || \
               grep -qiE "^COMPLETE — " "$fix_file" 2>/dev/null; then
                continue
            fi
            
            # Fix items always get rank 0 (highest priority per spec)
            rank="0"
            title=$(grep -m 1 -i '^title:' "$fix_file" 2>/dev/null | sed 's/^title:\s*//' || echo "Fix PR #$pr_num")
            branch=$(grep -m 1 -i '^branch:' "$fix_file" 2>/dev/null | awk '{print $2}' || echo "")
            echo "${rank:-0} $fix_file $title — fix for PR#$pr_num (branch: $branch)" >> "$PRIORITY_FILE"
        fi
    done
fi

# --- Tier 2: Ranked Feature Items (skip resolved) -----------------------------
# Scan both main backlog/ and proposed/ subdirectories
for dir in "$BACKLOG_DIR" "$BACKLOG_DIR/proposed"; do
    [ ! -d "$dir" ] && continue
    for f in "$dir"/*.md; do
        [ ! -f "$f" ] && continue
        base=$(basename "$f")
    
     # Skip README. Fix items are NOT skipped — they get rank 0 and sort first.
      [[ "$base" == "README.md" ]] && continue
    
      # Skip resolved/completed items — auto-resolved or manually marked done
      if grep -q "✅.*RESOLVED" "$f" 2>/dev/null || \
         grep -qiE "^.*(COMPLETE|RESOLVED)" "$f" 2>/dev/null; then
          continue
      fi
    
      # Fix items always get rank 0 (highest priority) regardless of explicit rank field
      is_fix="0"
      [[ "$base" == *fix* ]] && is_fix="1"
    
      if [ "$is_fix" = "1" ]; then
          rank="0"
      else
          rank=$(grep -m 1 -i '^rank:' "$f" 2>/dev/null | awk '{print $2}' || echo "999")
      fi
    title=$(grep -m 1 -i '^title:' "$f" 2>/dev/null | sed 's/^title:\s*//' || echo "$base")
    
    echo "${rank} ${BACKLOG_DIR}/$base $title" >> "$PRIORITY_FILE"
    done
done
# Close outer for dir loop above, inner for f loop on line before that

# Sort by rank (numeric), then filename (alpha). Deduplicate by filepath keeping first (Tier 1 entry preferred over Tier 2).
DEDUPED=$(sort -k1,1n -k2,2 "$PRIORITY_FILE" | awk '!seen[$2]++')

echo "=== AGENTIC-TRADING-DESK LOOP CONTEXT ==="
echo "(generated $(date -u +%Y-%m-%dT%H:%M:%SZ))"
echo ""

if [ -z "$DEDUPED" ]; then
    echo "No backlog items found. Create ranked items in backlog/ directory."
    exit 0
fi

# Show all candidates for transparency
echo "--- All Candidates ---"
echo "$DEDUPED" | while read line; do
    echo "  $line"
done
echo ""

TOP_ITEM=$(echo "$DEDUPED" | head -1)
RANK=$(echo "$TOP_ITEM" | awk '{print $1}')
FILEPATH=$(echo "$TOP_ITEM" | awk '{print $2}')
TITLE=$(echo "$TOP_ITEM" | cut -d' ' -f3-)

echo "=== SELECTED ==="
echo "Rank: $RANK"
echo "File: $FILEPATH"
echo "Title: $TITLE"
echo ""

# Output the full item content for context injection
if [ -f "$FILEPATH" ]; then
    cat "$FILEPATH"
else
    echo "(file not found, may have been removed)"
fi
