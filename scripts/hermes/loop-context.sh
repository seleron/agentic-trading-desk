#!/usr/bin/env bash
#
# loop-context.sh — preprocessor for the nightly improvement routine.
#
# Used as `hermes cron ... --script`: its stdout is injected into the agent's
# prompt each run. It does the MECHANICAL work (no reasoning) so the local LLM
# spends its budget on implementation, not discovery: current branch, the ONE
# selected top backlog item, the ratchet baseline, and the gate command.
#
# Mirrors Adverts-Project/scripts/hermes/loop-context.sh, adapted to this
# Python repo (lowercase `rank:` frontmatter; nightly selects only ranked,
# already-approved items in backlog/[0-9]*.md — proposals in backlog/proposed/
# are NOT implemented until the weekly review promotes them).

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

# The loop operates on this branch (NOT main); nightly branches from and PRs
# against it. Override with LOOP_BASE_BRANCH if you later move the loop's home.
LOOP_BASE_BRANCH="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"
export LOOP_BASE_BRANCH

echo "=== AUTONOMOUS LOOP CONTEXT (generated $(date -u +%FT%TZ)) ==="
echo "Repo: $ROOT"
echo "Branch (checkout): $(git rev-parse --abbrev-ref HEAD 2>/dev/null)"
echo "LOOP BASE BRANCH: $LOOP_BASE_BRANCH  (branch auto/<slug> from this, open PRs against this, NOT main)"
echo "Latest base commit: $(git log -1 --oneline "origin/$LOOP_BASE_BRANCH" 2>/dev/null || git log -1 --oneline "$LOOP_BASE_BRANCH" 2>/dev/null)"
echo

# Sweep out any items already shipped by a merged PR BEFORE selecting — otherwise
# the lowest-rank pick can land on an item whose PR already merged, and the run
# wastes the night "re-validating" a done item. Best-effort and quiet (reconcile
# self-guards to base+clean); the robust PR→item mapping lives in backlog-reconcile.sh.
bash "$ROOT/scripts/hermes/backlog-reconcile.sh" >/dev/null 2>&1 || true

# is_open <file> — false if the item is marked resolved/complete (belt-and-braces;
# reconcile normally deletes resolved files, but a manually-annotated one may linger).
is_open() {
  ! grep -qiE '✅[[:space:]]*(RESOLVED|COMPLETE)|(RESOLVED|COMPLETE)[[:space:]]*✅|^status:[[:space:]]*✅|^resolved:[[:space:]]*true' "$1" 2>/dev/null
}

echo "--- TOP BACKLOG ITEM (implement THIS one only) ---"
# Pick the open item with the lowest rank: (weekly review sets rank; review-fix
# items carry rank 0 so they always sort first). Tie-break by filename. Missing
# rank sorts last. ONLY top-level backlog/[0-9]*.md — proposals await approval.
TOP="$(for f in backlog/[0-9]*.md; do
  [ -e "$f" ] || continue
  is_open "$f" || continue
  rank=$(grep -m1 -iE '^rank:' "$f" | grep -oE '[0-9]+' | head -1)
  printf '%05d\t%s\n' "${rank:-99999}" "$f"
done | sort | head -1 | cut -f2)"

if [ -n "$TOP" ]; then
  echo "File: $TOP"
  echo "PR-BODY MARKER — paste this line verbatim into the PR body so the item is auto-removed on merge:"
  # A review-fix item embeds its own Resolves-Backlog line carrying the original
  # feature stem(s) too — emit that verbatim so the feature item isn't orphaned
  # when the fix-round PR body overwrites the marker. Else default to the basename.
  MARKER="$(grep -m1 -iE '^Resolves-Backlog:' "$TOP" 2>/dev/null || true)"
  [ -z "$MARKER" ] && MARKER="Resolves-Backlog: $(basename "$TOP" .md)"
  echo "$MARKER"
  echo
  cat "$TOP"
else
  echo "(no open backlog items — nothing to do; reply [SILENT])"
fi
echo

echo "--- RATCHET BASELINE (must not regress) ---"
[ -f metrics/baseline.json ] && python3 -c "import json;b=json.load(open('metrics/baseline.json'));print('minTests:', b.get('minTests','(unset)'))" 2>/dev/null
echo

echo "--- GATE ---"
echo "Validate with: bash scripts/ci.sh   (must print GATE PASSED)"
echo "=== END CONTEXT ==="
