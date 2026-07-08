#!/usr/bin/env bash
#
# health-watch.sh — watchdog for the autonomous LOOP (this project has no live
# always-on service to curl; the loop itself is what must stay healthy).
#
# Designed for `hermes cron ... --no-agent --script`: prints NOTHING when
# everything is healthy (silent = no notification), and prints an alert line only
# when something is wrong. No LLM involved.
#
# Checks:
#   1. Reconcile merged PRs quietly (catches human merges → removes done items).
#   2. Origin reachable + gh authenticated (a broken remote silently kills the loop).
#   3. The base branch exists on origin (nightly branches from it).
#   4. Any open auto/* PR escalated to ⛔ needs-human (hit MAX_ROUNDS) — so a stuck
#      PR doesn't rot unseen.
#   5. The main checkout isn't stuck detached / mid-rebase from a crashed cron.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
BASE="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || echo seleron/agentic-trading-desk)"
ALERT=""

# 1. Reconcile merged PRs (quiet; removes resolved backlog items, catches human merges).
bash "$ROOT/scripts/hermes/backlog-reconcile.sh" >/dev/null 2>&1 || true

# 2. Origin reachable + gh authenticated.
if ! git ls-remote --exit-code origin >/dev/null 2>&1; then
  ALERT+="⚠️ trading loop: git origin unreachable (fetch/auth broken) — the loop is stalled"$'\n'
fi
if ! gh auth status >/dev/null 2>&1; then
  ALERT+="⚠️ trading loop: gh CLI not authenticated — PR review/merge is stalled"$'\n'
fi

# 3. Base branch exists on origin.
if ! git ls-remote --exit-code --heads origin "$BASE" >/dev/null 2>&1; then
  ALERT+="⚠️ trading loop: base branch origin/$BASE is missing — nightly cannot branch from it"$'\n'
fi

# 4. Open auto/* PRs escalated to needs-human (MAX_ROUNDS reached without resolution).
STUCK="$(gh pr list --repo "$REPO" --state open --base "$BASE" \
  --json number,headRefName,comments \
  --jq '.[] | select(.headRefName|startswith("auto/")) | select([.comments[]|select(.body|test("Needs human|NEEDS HUMAN|hit .* review rounds"))]|length>0) | "#\(.number) \(.headRefName)"' 2>/dev/null || true)"
if [ -n "$STUCK" ]; then
  ALERT+="🧑‍⚖️ trading loop: PR(s) awaiting a human decision (auto-fix paused):"$'\n'"$STUCK"$'\n'
fi

# 5. Main checkout not stuck detached / mid-op from a crashed cron.
if [ -d "$ROOT/.git" ] || [ -f "$ROOT/.git" ]; then
  HEAD_REF="$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo unknown)"
  [ "$HEAD_REF" = "HEAD" ] && ALERT+="⚠️ trading loop: main checkout is in DETACHED HEAD — a cron may have crashed mid-op"$'\n'
  { [ -d "$ROOT/.git/rebase-merge" ] || [ -d "$ROOT/.git/rebase-apply" ]; } \
    && ALERT+="⚠️ trading loop: an unfinished git rebase is in progress in the main checkout"$'\n'
fi

if [ -n "$ALERT" ]; then
  printf '%s' "$ALERT"
  exit 0   # the alert text is the deliverable, not a script failure
fi
# Healthy → silent (no notification).
