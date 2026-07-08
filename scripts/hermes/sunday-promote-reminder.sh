#!/usr/bin/env bash
#
# sunday-promote-reminder.sh — weekly nudge (Sun 19:30) to promote
# autonomous/scaffolding → main after a week of validation. Runs as a --no-agent
# cron; its stdout is delivered to the user. Also shows what's pending.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"; cd "$ROOT"
SRC="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"

git fetch origin main "$SRC" -q 2>/dev/null || true
AHEAD="$(git rev-list --count "origin/main..origin/$SRC" 2>/dev/null || echo 0)"

echo "🗓️ Sunday promote check — agentic-trading-desk"
if [ "${AHEAD:-0}" -eq 0 ]; then
  echo "main is already up to date with $SRC — nothing to promote this week."
else
  echo "$SRC is $AHEAD commit(s) ahead of main. This week's improvements:"
  git log --oneline "origin/main..origin/$SRC" 2>/dev/null | head -20
  echo
  echo "If a week of validation looks good, reply \"merge trading to main\" and I'll promote it."
fi
