#!/usr/bin/env bash
#
# pr-review-poll.sh — trigger for the PR-review loop (poll-based; runs as a
# --no-agent cron). Finds open auto/* draft PRs whose HEAD commit hasn't been
# reviewed yet and runs pr-review-dispatch.sh on each. Dedups by PR#:sha so
# the same commit is never reviewed twice. Prints a per-PR summary
# (delivered to the user); stays silent when there's nothing new.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
BASE="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"
STATE="$HOME/.hermes/agentic-trading-pr-reviewed.txt"
touch "$STATE"

mapfile -t PRS < <(gh pr list --repo seleron/agentic-trading-desk --state open \
  --json number,headRefName,headRefOid \
  --jq '.[] | "\( .number ) \( .headRefOid )" ' 2>/dev/null || true)

ANY=0
for line in "${PRS[@]}"; do
  [ -z "$line" ] && continue
  NUM="${line%% *}"; SHA="${line##* }"

  # Re-dispatch trigger: a NEW HEAD commit (normal case) OR — when the last review
  # was NEEDS_HUMAN — a new owner answer in the PR (a comment doesn't change the sha,
  # so key the dedup off the latest comment timestamp instead).
  KEY="$NUM:$SHA"
  LAST_REVIEW="$(gh pr view "$NUM" --json comments \
    --jq '[.comments[] | select(.body|test("[BOT] Claude review"))] | last | .body' 2>/dev/null || true)"
  if printf '%s' "$LAST_REVIEW" | grep -q 'NEEDS_HUMAN'; then
    ANSWER_AT="$(gh pr view "$NUM" --json comments \
      --jq '[.comments[] | select((.body|test("[BOT] Claude review|Needs human|NEEDS HUMAN"))|not) | .createdAt]' 2>/dev/null || true)"
    [ -n "$ANSWER_AT" ] && KEY="$NUM:answer:$ANSWER_AT"
  fi

  grep -qx "$KEY" "$STATE" && continue               # already handled this head / answer
  # Mark at dispatch time so we don't re-trigger while the (slow) review runs,
  # and DETACH it: a review re-runs the gate for minutes, but Hermes kills this
  # --script job at 120s. setsid survives this script's exit.
  echo "$KEY" >> "$STATE"
  setsid bash "$ROOT/scripts/hermes/pr-review-dispatch.sh" "$NUM" >/dev/null 2>&1 < /dev/null &
  echo "dispatched async review for PR #$NUM (${KEY})"
  ANY=1
done
disown -a 2>/dev/null || true

[ "$ANY" = 0 ] && echo "[SILENT]"   # nothing new → suppress delivery
exit 0
