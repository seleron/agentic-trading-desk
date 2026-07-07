#!/usr/bin/env bash
#
# backlog-reconcile.sh — Auto-resolve backlog items when their linked PRs merge.
#
# Called after a PR auto-merge (from pr-review.sh) or on-demand.
# Scans backlog/ for items whose Resolves-Backlog line references the merged PR,
# then marks them ✅ RESOLVED with merge date and branch info.
#
# Usage:
#   backlog-reconcile.sh [pr-number]  — reconcile all, or just this PR's items
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
TARGET_PR="${1:-}"

log(){ printf '%s\n' "$*" >&2; }

# --- Find merged PR numbers (last 7 days, from origin/main) ------------------
MERGED_PRS=()
if [ -z "$TARGET_PR" ]; then
    # Scan recent merge commits on main for PR references
    MERGED_FROM_MAIN=$(git log --oneline --since="7 days ago" "origin/main" \
        --grep='^Merge pull request' 2>/dev/null | \
        grep -oE '#[0-9]+' | tr -d '#' || true)
    
    # Also check PR API for recently merged ones targeting main or scaffolding
    GH_MERGED=$(gh pr list --repo seleron/agentic-trading-desk --state merged --json number,baseRefName,state 2>/dev/null || echo "[]")
    while IFS= read -r line; do
        [ -z "$line" ] && continue
        NUM=$(echo "$line" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["number"])' 2>/dev/null || true)
        BASE=$(echo "$line" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["baseRefName"])' 2>/dev/null || true)
        STATE=$(echo "$line" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["state"])' 2>/dev/null || true)
        if [ "$STATE" = "MERGED" ] && ([ "$BASE" = "main" ] || [ "$BASE" = "autonomous/scaffolding" ]); then
            MERGED_PRS+=("$NUM")
        fi
    done < <(echo "$GH_MERGED" | python3 -c 'import sys,json;[print(json.dumps(x)) for x in json.load(sys.stdin)]' 2>/dev/null || true)
    
    # Combine both sources (deduplicate)
    MERGED_PRS=$(printf '%s\n' "${MERGED_PRS[@]}" "$MERGED_FROM_MAIN" | tr ' ' '\n' | sed '/^$/d' | sort -un | paste -sd' ')
else
    # Specific PR — verify it's merged
    STATE=$(gh pr view "$TARGET_PR" --json state --jq '.state' 2>/dev/null || echo "")
    if [ "$STATE" = "MERGED" ]; then
        MERGED_PRS="$TARGET_PR"
    else
        log "PR #$TARGET_PR is $STATE — nothing to reconcile"
        exit 0
    fi
fi

[ -z "$(echo "$MERGED_PRS" | tr -d '[:space:]')" ] && { log "[SILENT] No merged PRs found"; exit 0; }

MERGE_DATE=$(date -u +%Y-%m-%dT%H:%M:%SZ)
RESOLVED_COUNT=0

# --- Process each backlog item -----------------------------------------------
for f in "$ROOT"/backlog/*.md; do
    [ ! -f "$f" ] && continue
    
    # Skip README and proposed items
    [[ "$(basename "$f")" == "README.md" ]] && continue
    [[ "$(dirname "$f")" == *"proposed"* ]] && continue
    
    # Check if this item references any of our merged PRs
    for pr_num in $MERGED_PRS; do
        # Match patterns: "PR: #X", "Resolves-Backlog: X", or filename containing fix-prX
        MATCH=0
        
        # Pattern 1: PR header line matching this PR number
        if grep -qiE "^PR:[[:space:]]*#?${pr_num}([^0-9]|$)" "$f" 2>/dev/null; then
            MATCH=1
        fi
        
        # Pattern 2: Resolves-Backlog contains the item stem for this PR
        if [ $MATCH -eq 0 ] && grep -qiE "^Resolves-Backlog:" "$f" 2>/dev/null; then
            STEMS=$(grep -iE "^Resolves-Backlog:" "$f" | sed 's/^[^:]*://' | tr ',' ' ')
            for stem in $STEMS; do
                if echo "$stem" | grep -qi "fix-pr${pr_num}"; then
                    MATCH=1
                    break
                fi
            done
        fi
        
        # Pattern 3: Filename contains fix-prX (for items like 008-fix-pr2.md)
        if [ $MATCH -eq 0 ]; then
            BASENAME=$(basename "$f" .md)
            if echo "$BASENAME" | grep -qiE "fix-pr${pr_num}"; then
                MATCH=1
            fi
        fi
        
        # Pattern 4: Body mentions the PR branch name or specific fix keywords
        if [ $MATCH -eq 0 ]; then
            BRANCH=$(gh pr view "$TARGET_PR" --json headRefName --jq '.headRefName' 2>/dev/null || echo "")
            if grep -qi "feature/.*${pr_num}" "$f" 2>/dev/null || \
               grep -qi "PR #${pr_num}" "$f" 2>/dev/null; then
                MATCH=1
            fi
        fi
        
        if [ $MATCH -eq 1 ]; then
             # Check if already resolved (both RESOLVED and COMPLETE patterns)
             ALREADY_DONE=0
             if grep -q "✅.*RESOLVED" "$f" 2>/dev/null; then
                 ALREADY_DONE=1
             fi
             # Also check for old COMPLETE pattern
             if grep -qiE "^COMPLETE — " "$f" 2>/dev/null || grep -qiE "^## Status\nCOMPLETE" "$f" 2>/dev/null; then
                 ALREADY_DONE=1
             fi
            
             if [ $ALREADY_DONE -eq 1 ]; then
                 log "  SKIP $f — already resolved"
                 continue
             fi
            # Mark as resolved
            if grep -q "^## Status" "$f" 2>/dev/null; then
                # Update existing status block
                sed -i "s/^## Status$/## Status/" "$f"
                sed -i "/^## Status/a\\✅ **RESOLVED** — PR #$pr_num merged at $MERGE_DATE." "$f"
            else
                # Append status section
                printf '\n## Status\n✅ **RESOLVED** — PR #%s merged at %s.\n' "$pr_num" "$MERGE_DATE" >> "$f"
            fi
            
            RESOLVED_COUNT=$((RESOLVED_COUNT + 1))
            log "  ✅ RESOLVED $f (PR #$pr_num)"
        fi
    done
done

if [ $RESOLVED_COUNT -gt 0 ]; then
    # Commit the resolution
    if git add "$ROOT"/backlog/ && \
       git commit -q -m "reconcile: auto-resolved $RESOLVED_COUNT backlog item(s) from merged PRs" 2>/dev/null; then
        log "Committed resolution changes."
    fi
fi

[ $RESOLVED_COUNT -eq 0 ] && echo "[SILENT]" || echo "✅ Resolved $RESOLVED_COUNT backlog items from merged PRs"
exit 0
