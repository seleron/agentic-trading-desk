#!/usr/bin/env bash
#
# promote-to-main.sh — the weekly production merge: autonomous/scaffolding → main.
#
# Runs in an ISOLATED worktree (the live loop checkout is untouched), merges the
# base branch into main, runs the deterministic gate as a safety check, and pushes
# main. Resolves trivial fast-forwards automatically; on a real conflict or a gate
# failure it stops SAFELY (prints ⛔ and a reason) — a human must look.
#
# Prints exactly one final line:
#   ✅ Promoted …             — main advanced; redeploy/announce as you like.
#   ✅ Nothing to promote …   — main already current.
#   ⛔ …                       — stopped safely (gate fail / conflict / push fail).
#
# Never push to main directly or bypass this script.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/hermes/lib-loop.sh"
SRC="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"
WT="$(cd "$(dirname "$ROOT")" && pwd)/agentic-trading-promote"
log(){ printf '%s\n' "$*" >&2; }

git fetch origin main "$SRC" -q 2>/dev/null || { echo "⛔ Could not fetch origin (main/$SRC) — aborted."; exit 1; }

AHEAD="$(git rev-list --count "origin/main..origin/$SRC" 2>/dev/null || echo 0)"
if [ "${AHEAD:-0}" -eq 0 ]; then
  echo "✅ Nothing to promote — origin/main is already up to date with $SRC."
  exit 0
fi

{ flock 9
  git worktree remove --force "$WT" >/dev/null 2>&1 || true; [ -d "$WT" ] && rm -rf "$WT"
  git worktree add -B __promote_main "$WT" origin/main >/dev/null 2>&1 || {
    echo "⛔ Could not create promote worktree from origin/main — aborted."; exit 1; }
} 9>"$LOOP_LOCK"

STATUS="⛔ Promote failed for an unknown reason — a human must look."
if git -C "$WT" merge --no-edit "origin/$SRC" >/tmp/promote-merge.log 2>&1; then
  log "Merged origin/$SRC into main cleanly; running the safety gate…"
  if ( cd "$WT" && timeout 420 bash scripts/ci.sh >/tmp/promote-gate.log 2>&1 ); then
    if git -C "$WT" push origin HEAD:main >/tmp/promote-push.log 2>&1; then
      NEWSHA="$(git -C "$WT" rev-parse --short HEAD)"
      STATUS="✅ Promoted $SRC → main ($AHEAD commit(s), now at $NEWSHA). Gate passed."
    else
      STATUS="⛔ Gate passed but push to main FAILED — see /tmp/promote-push.log. Not retried."
    fi
  else
    STATUS="⛔ Safety gate FAILED on the merged result — main NOT advanced. See /tmp/promote-gate.log."
  fi
else
  git -C "$WT" merge --abort >/dev/null 2>&1 || true
  STATUS="⛔ Merge conflict promoting $SRC → main — resolve by hand. See /tmp/promote-merge.log."
fi

{ flock 9
  git worktree remove --force "$WT" >/dev/null 2>&1 || true; [ -d "$WT" ] && rm -rf "$WT"
  git branch -D __promote_main >/dev/null 2>&1 || true
} 9>"$LOOP_LOCK"

echo "$STATUS"
