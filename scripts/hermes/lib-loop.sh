#!/usr/bin/env bash
#
# lib-loop.sh — shared helpers for the autonomous loop scripts. Source it:
#     source "$(dirname "${BASH_SOURCE[0]}")/lib-loop.sh"
#
# Provides a single git mutex so the nightly, weekly, reviews, reconcile, and
# worktree ops never mutate the live checkout's index/refs at the same time.

LOOP_LOCK="${LOOP_LOCK:-$HOME/.hermes/agentic-trading-git.lock}"

with_git_lock() {
  flock "$LOOP_LOCK" "$@"
}
