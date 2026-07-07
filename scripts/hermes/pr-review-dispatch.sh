#!/usr/bin/env bash
#
# pr-review-dispatch.sh <pr-number> — run one PR review (slow) and Telegram the
# result. Launched DETACHED (setsid) by pr-review-poll.sh so the review's
# multi-minute gate re-run never blocks Hermes' 120s --script timeout.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PR="${1:?usage: pr-review-dispatch.sh <pr-number>}"
LOG="$HOME/.hermes/pr-review-$PR.log"

# Load delivery target from loop.env
if [ -f "$ROOT/scripts/hermes/loop.env" ]; then
  source "$ROOT/scripts/hermes/loop.env"
fi

if command -v hermes >/dev/null 2>&1; then HSEND=(hermes send)
else HSEND=("$HOME/.hermes/hermes-agent/venv/bin/python" -m hermes_cli.main send); fi

OUT="$(bash "$ROOT/scripts/hermes/pr-review.sh" "$PR" 2>"$LOG" | tail -1)"
if [ -n "${HERMES_DELIVER:-}" ]; then
  "${HSEND[@]}" -t "$HERMES_DELIVER" "PR #$PR review — ${OUT:-see PR comment}" >/dev/null 2>&1 || true
else
  echo "⚠️ no delivery target (set HERMES_DELIVER in scripts/hermes/loop.env)" >&2
fi
