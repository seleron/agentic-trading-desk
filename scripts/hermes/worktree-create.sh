#!/usr/bin/env bash
#
# worktree-create.sh <slug> [existing-branch] — isolated worktree for the loop.
#
# Prints the worktree's ABSOLUTE path on the last stdout line (logs go to
# stderr). This is the robustness fix for Hermes' non-persistent shells: the
# caller copies that absolute path literally and uses `git -C <path>` for
# everything, never relying on `cd` or env vars surviving between commands.
#
#   - no existing-branch: create a fresh branch auto/<slug> from the base.
#   - existing-branch (e.g. auto/foo): check that branch out to UPDATE an open
#     PR (used by review-fix items that carry a `Branch:` field).
#
# Idempotent: reuses an already-checked-out branch, else cleans up stale
# worktrees and (re)creates with `worktree add -B`.
#
# Mirrors Adverts-Project/scripts/hermes/worktree-create.sh (Python repo: no
# node_modules to link; worktree-setup.sh just verifies importable deps).

set -euo pipefail
SLUG="${1:?usage: worktree-create.sh <slug> [existing-branch]}"
EXISTING="${2:-}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"
WT="$(cd "$(dirname "$ROOT")" && pwd)/agentic-trading-auto-$SLUG"
source "$ROOT/scripts/hermes/lib-loop.sh"

# Serialize worktree metadata mutations against the rest of the loop.
{ flock 9
  REUSE=""
  if [ -n "$EXISTING" ]; then
    REUSE="$(git -C "$ROOT" worktree list --porcelain \
      | awk -v b="refs/heads/$EXISTING" \
          '/^worktree /{wt=substr($0,10)} /^branch /{if($2==b){print wt; exit}}')" || REUSE=""
  fi
  if [ -n "$REUSE" ]; then
    echo "reusing existing worktree $REUSE for branch $EXISTING (updating its PR) ..." >&2
    git -C "$REUSE" fetch origin "$EXISTING" >/dev/null 2>&1 || true
    # Hard-reset to the latest pushed state BEFORE the agent edits, so the later
    # push to the PR branch fast-forwards instead of being rejected as non-ff.
    git -C "$REUSE" reset --hard "origin/$EXISTING" >&2 \
      || git -C "$REUSE" reset --hard FETCH_HEAD >&2 || true
    WT="$REUSE"
  else
    git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
    git -C "$ROOT" worktree prune >/dev/null 2>&1 || true
    rm -rf "$WT" 2>/dev/null || true
    if [ -n "$EXISTING" ]; then
      echo "creating worktree $WT on EXISTING branch $EXISTING (updating its PR) ..." >&2
      git -C "$ROOT" fetch origin "$EXISTING" >/dev/null 2>&1 || true
      git -C "$ROOT" worktree add -B "$EXISTING" "$WT" "origin/$EXISTING" >&2
    else
      echo "creating worktree $WT on new branch auto/$SLUG from $BASE ..." >&2
      git -C "$ROOT" fetch origin "$BASE" >/dev/null 2>&1 || true
      git -C "$ROOT" worktree add -B "auto/$SLUG" "$WT" "origin/$BASE" >&2 \
        || git -C "$ROOT" worktree add -B "auto/$SLUG" "$WT" "$BASE" >&2
    fi
  fi
} 9>"$LOOP_LOCK"
( cd "$WT" && bash scripts/hermes/worktree-setup.sh >&2 ) || true

# stdout: ONLY the absolute worktree path (the caller captures/uses this).
echo "$WT"
