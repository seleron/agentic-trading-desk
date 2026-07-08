#!/usr/bin/env bash
#
# pr-review-poll.sh — trigger for the PR-review loop (poll-based; runs as a
# --no-agent cron). Finds open auto/* draft PRs whose HEAD commit hasn't been
# reviewed yet and dispatches pr-review on each. Dedups by PR#:sha so the same
# commit is never reviewed twice. Prints a per-PR summary (delivered to the
# user); stays silent when there's nothing new.
#
# Webhooks would be more "instant" but need a public endpoint this box lacks;
# the loop is nightly-paced, so polling is functionally equivalent.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
BASE="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || echo seleron/agentic-trading-desk)"
STATE="$HOME/.hermes/agentic-trading-pr-reviewed.txt"
touch "$STATE"
REVIEW_HEADER="🤖 Claude Opus 4.8 review"   # MUST match pr-review.sh REVIEW_HEADER

# First, reconcile any merged PRs (remove their resolved backlog items) — covers
# human merges as well as auto-merges.
RECON="$(bash "$ROOT/scripts/hermes/backlog-reconcile.sh" 2>&1 | grep -E '^PR #|removed ' || true)"
[ -n "$RECON" ] && printf 'reconciled merged PRs:\n%s\n' "$RECON"

# Open PRs whose HEAD branch is an auto/* branch and whose base is $BASE.
mapfile -t PRS < <(gh pr list --repo "$REPO" --state open --base "$BASE" \
  --json number,headRefName,headRefOid \
  --jq '.[] | select(.headRefName|startswith("auto/")) | "\(.number) \(.headRefOid)"' 2>/dev/null || true)

ANY=0
for line in "${PRS[@]}"; do
  [ -z "$line" ] && continue
  NUM="${line%% *}"; SHA="${line##* }"

  # Re-dispatch trigger: a NEW HEAD commit (normal case) OR — when the last review
  # was NEEDS_HUMAN — a new owner answer in the PR (a comment doesn't change the
  # sha, so key the dedup off the latest owner-comment timestamp instead).
  KEY="$NUM:$SHA"
  LAST_REVIEW="$(gh pr view "$NUM" --json comments \
    --jq "[.comments[] | select(.body|test(\"$REVIEW_HEADER\"))] | last | .body" 2>/dev/null || true)"
  if printf '%s' "$LAST_REVIEW" | grep -q 'NEEDS_HUMAN'; then
    ANSWER_AT="$(gh pr view "$NUM" --json comments \
      --jq "[.comments[] | select((.body|test(\"$REVIEW_HEADER|Needs human|NEEDS HUMAN\"))|not)] | last | .createdAt" 2>/dev/null || true)"
    [ -n "$ANSWER_AT" ] && KEY="$NUM:answer:$ANSWER_AT"
  fi

  grep -qx "$KEY" "$STATE" && continue               # already handled this head / answer
  # Mark at dispatch time so we don't re-trigger while the (slow) review runs, and
  # DETACH it: a review re-runs the gate for minutes, but Hermes kills this --script
  # job at ~120s. setsid survives this script's exit.
  echo "$KEY" >> "$STATE"
  setsid bash "$ROOT/scripts/hermes/pr-review-dispatch.sh" "$NUM" >/dev/null 2>&1 < /dev/null &
  echo "dispatched async review for PR #$NUM (${KEY})"
  ANY=1
done
disown -a 2>/dev/null || true

[ "$ANY" = 0 ] && echo "[SILENT]"   # nothing new → suppress delivery
exit 0
