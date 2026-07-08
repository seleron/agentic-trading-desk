#!/usr/bin/env bash
#
# pr-review-dispatch.sh <pr-number> — run one PR review (slow) and Telegram the
# result. Launched DETACHED (setsid) by pr-review-poll.sh so the review's
# multi-minute gate re-run never blocks Hermes' ~120s --script timeout.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
# Host config (delivery target etc.) — gitignored; see loop.env.example.
[ -f "$ROOT/scripts/hermes/loop.env" ] && { set -a; . "$ROOT/scripts/hermes/loop.env"; set +a; }
PR="${1:?usage: pr-review-dispatch.sh <pr-number>}"
TARGET="${PR_REVIEW_NOTIFY:-${HERMES_DELIVER:-}}"
LOG="$HOME/.hermes/pr-review-$PR.log"

if command -v hermes >/dev/null 2>&1; then HSEND=(hermes send)
else HSEND=("$HOME/.hermes/hermes-agent/venv/bin/python" -m hermes_cli.main send); fi

OUT="$(bash "$ROOT/scripts/hermes/pr-review.sh" "$PR" 2>"$LOG" | tail -1)"
if [ -n "$TARGET" ]; then
  "${HSEND[@]}" -t "$TARGET" "🤖 PR #$PR review — ${OUT:-see PR comment}" >/dev/null 2>&1 || true
else
  echo "⚠️ no delivery target (set HERMES_DELIVER/PR_REVIEW_NOTIFY in scripts/hermes/loop.env)" >&2
fi
