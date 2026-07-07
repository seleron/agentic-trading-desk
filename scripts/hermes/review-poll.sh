#!/bin/bash
# PR review poll for agentic-trading-desk — checks open PRs and reports status

set -euo pipefail

cd /home/seleron/Desktop/agentic-trading-desk

OPEN_PRS=$(gh pr list --repo seleron/agentic-trading-desk --state open --json number,title,headRefName,statusCheckRollup,reviewDecision,reviews --jq '.' 2>/dev/null || echo "[]")
PR_COUNT=$(echo "$OPEN_PRS" | jq 'length' 2>/dev/null || echo "0")

if [ "$PR_COUNT" -eq 0 ]; then
    exit 0  # Silent — no PRs to review
fi

echo "=== Agentic Trading Desk — PR Review Poll ==="
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

echo "$OPEN_PRS" | jq -r '.[] | "#\(.number): \(.title) (branch: \(.headRefName))"' 

# Check for PRs that need attention (no review or changes requested)
NEEDS_ATTENTION=$(echo "$OPEN_PRS" | jq '[.[] | select(.reviewDecision == null or .reviewDecision == "CHANGES_REQUESTED")] | length' 2>/dev/null || echo "0")

if [ "$NEEDS_ATTENTION" -gt 0 ]; then
    echo ""
    echo "⚠️ $NEEDS_ATTENTION PR(s) need review attention:"
    echo "$OPEN_PRS" | jq -r '.[] | select(.reviewDecision == null or .reviewDecision == "CHANGES_REQUESTED") | "  #\(.number): \(.title) — status: \(.reviewDecision // "no_review")"' 
fi

# Check CI status (if any checks exist)
CHECKS_RUNNING=$(echo "$OPEN_PRS" | jq '[.[] | select(.statusCheckRollup != null and (.statusCheckRollup | length > 0))] | length' 2>/dev/null || echo "0")
if [ "$CHECKS_RUNNING" -gt 0 ]; then
    echo ""
    echo "ℹ️ $CHECKS_RUNNING PR(s) have status checks running (no CI configured — normal)"
fi

echo ""
echo "Done."
