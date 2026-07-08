#!/usr/bin/env bash
#
# worktree-remove.sh <abs-worktree-path> — tear down a loop worktree.
# Keeps the branch (it backs the PR); only removes the working tree. Safe to call
# even if already gone. Uses `git -C` so it works from any cwd.

set -euo pipefail
WT="${1:?usage: worktree-remove.sh <abs-worktree-path>}"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
source "$ROOT/scripts/hermes/lib-loop.sh"

{ flock 9
  git -C "$ROOT" worktree remove --force "$WT" >/dev/null 2>&1 || true
  git -C "$ROOT" worktree prune >/dev/null 2>&1 || true
  rm -rf "$WT" 2>/dev/null || true
} 9>"$LOOP_LOCK"
echo "removed worktree $WT" >&2
