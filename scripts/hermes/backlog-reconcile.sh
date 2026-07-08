#!/usr/bin/env bash
#
# backlog-reconcile.sh [pr-number] — remove backlog items resolved by merged PRs.
#
#   no arg     : scan recently MERGED auto/* PRs into the base branch and
#                reconcile any not done yet (catches human merges too).
#   pr-number  : reconcile just that (already-merged) PR (used right after an
#                auto-merge for promptness).
#
# An item is resolved by PR #N when either:
#   - PR #N's body has a `Resolves-Backlog: <stems/numbers>` marker, or
#   - the item file has a `PR: #N` line (review-fix items), or
#   - PR #N's body says "backlog item NNN" and backlog/NNN-*.md exists (fallback).
#
# Resolved items are DELETED (git rm) and the removal is committed+pushed to the
# base branch under the loop git-lock. Set DRY_RUN=1 to preview without changes.
#
# Mirrors Adverts-Project/scripts/hermes/backlog-reconcile.sh.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/hermes/lib-loop.sh"
BASE="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || echo seleron/agentic-trading-desk)"
STATE="$HOME/.hermes/agentic-trading-reconciled-prs.txt"; touch "$STATE"
DRY="${DRY_RUN:-0}"
# Only mutate files when the checkout is actually on the base branch — otherwise a
# reconcile triggered from a feature-branch checkout (loop-context / health-watch
# run from whatever branch is out) would `git rm` files it can never commit,
# leaving the tree dirty. Off-base runs report only; the next on-base run acts.
ON_BASE=0
[ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$BASE" ] && ON_BASE=1

# Best-effort: fast-forward local base to origin so our removal commit pushes
# cleanly (picks up any just-merged PR). Only when on a clean base checkout.
git fetch origin "$BASE" -q 2>/dev/null || true
if [ "$DRY" != "1" ] && [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$BASE" ] \
   && [ -z "$(git status --porcelain 2>/dev/null)" ]; then
  { flock 9; git merge --ff-only "origin/$BASE" -q 2>/dev/null || true; } 9>"$LOOP_LOCK"
fi

resolve_items_for_pr() {  # echoes backlog file paths resolved by PR $1
  local num="$1" body marker tok f n
  body="$(gh pr view "$num" --json body --jq .body 2>/dev/null || true)"
  marker="$(printf '%s' "$body" | grep -ioE 'Resolves-Backlog:.*' | sed -E 's/^[^:]*://' || true)"
  # marker stems/numbers → files
  for tok in $(printf '%s' "$marker" | tr ',' ' '); do
    tok="$(printf '%s' "$tok" | tr -cd 'A-Za-z0-9-')"
    [ -z "$tok" ] && continue
    for f in backlog/*"$tok"*.md; do [ -e "$f" ] && echo "$f"; done
  done
  # review-fix items that name this PR
  for f in backlog/[0-9]*.md; do
    [ -e "$f" ] || continue
    grep -qE "^PR:[[:space:]]*#?$num([^0-9]|$)" "$f" 2>/dev/null && echo "$f"
  done
  # Fallback: body says "backlog item NNN" and that file exists. Constrained to
  # that literal phrase + an existing file so it can only remove an item the PR
  # explicitly claims (the local LLM sometimes ships without the marker).
  for n in $(printf '%s' "$body" | grep -ioE 'backlog item[^0-9]{0,6}[0-9]{3}' | grep -oE '[0-9]{3}' | sort -u); do
    for f in backlog/"$n"-*.md; do [ -e "$f" ] && echo "$f"; done
  done
}

reconcile_pr() {  # $1 = merged PR number
  local num="$1" items f
  items="$(resolve_items_for_pr "$num" | sort -u | grep -v '^$' || true)"
  if [ -z "$items" ]; then echo "  PR #$num: no backlog items to remove" >&2; return; fi
  while IFS= read -r f; do
    [ -z "$f" ] && continue
    if [ "$DRY" = "1" ]; then echo "  [dry] would remove $f (PR #$num)" >&2
    elif [ "$ON_BASE" != "1" ]; then echo "  [skip] $f resolved by PR #$num but checkout is not on $BASE — deferring removal" >&2
    else git rm -q "$f" 2>/dev/null || rm -f "$f"; echo "  removed $f (PR #$num merged)" >&2; fi
  done <<< "$items"
  echo "PR #$num → resolved $(echo "$items" | tr '\n' ' ')"
}

if [ -n "${1:-}" ]; then
  # Verify the specified PR is actually merged before removing its items.
  ST="$(gh pr view "$1" --json state --jq .state 2>/dev/null || echo '')"
  if [ "$ST" = "MERGED" ]; then reconcile_pr "$1"; else echo "PR #$1 is ${ST:-unknown} — nothing to reconcile" >&2; fi
else
  mapfile -t MERGED < <(gh pr list --repo "$REPO" --state merged --base "$BASE" --limit 30 \
    --json number,headRefName --jq '.[]|select(.headRefName|startswith("auto/"))|.number' 2>/dev/null || true)
  for num in "${MERGED[@]}"; do
    [ -z "$num" ] && continue
    grep -qx "$num" "$STATE" && continue
    reconcile_pr "$num"
    # Only record as done when we actually acted (on base, not dry) — otherwise a
    # deferred off-base run would permanently mark it reconciled and never remove it.
    [ "$DRY" != "1" ] && [ "$ON_BASE" = "1" ] && echo "$num" >> "$STATE"
  done
fi

# Commit + push removals (only on the base branch, only if something changed).
if [ "$DRY" != "1" ] && [ -n "$(git status --porcelain backlog/ 2>/dev/null)" ] \
   && [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$BASE" ]; then
  { flock 9
    # -u: stage only deletions/modifications of tracked items — NEVER sweep
    # untracked new backlog items someone is drafting into this commit.
    git add -u backlog/ >/dev/null 2>&1
    git commit -q -m "backlog: resolve items for merged PR(s)" >/dev/null 2>&1 || true
    git push -q origin "HEAD:$BASE" >/dev/null 2>&1 && echo "  pushed backlog resolution" >&2 || true
  } 9>"$LOOP_LOCK"
fi
