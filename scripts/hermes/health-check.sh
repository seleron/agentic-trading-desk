#!/bin/bash
# Health check for agentic-trading-desk autonomous loop
# Checks: repo state, last run time, PR status

export PATH="$HOME/.local/bin:$PATH"
set -euo pipefail

REPO_DIR="$(cd "$(dirname "$0")/../.." && pwd)"
LOG_FILE="$HOME/.hermes/cron/output/agentic-trading-desk-health.log"

cd "$REPO_DIR"

echo "=== Agentic Trading Desk — Health Check ==="
echo "Time: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
echo ""

# Check if scaffolding branch exists and is pushed
if ! git rev-parse --verify autonomous/scaffolding >/dev/null 2>&1; then
    echo "⚠️ No autonomous/scaffolding branch found"
else
    # Check last commit on scaffolding
    LAST_COMMIT=$(git log --oneline -1 autonomous/scaffolding 2>/dev/null || echo "")
    if [ -n "$LAST_COMMIT" ]; then
        COMMIT_DATE=$(git log -1 --format=%ci autonomous/scaffolding)
        echo "✅ Scaffolding branch: $LAST_COMMIT ($COMMIT_DATE)"
        
        # Check if pushed to origin
        LOCAL_SHA=$(git rev-parse autonomous/scaffording 2>/dev/null || true)
        ORIGIN_SHA=$(git rev-parse origin/autonomous/scaffolding 2>/dev/null || true)
        if [ "$LOCAL_SHA" = "$ORIGIN_SHA" ] 2>/dev/null; then
            echo "✅ Branch is pushed to origin"
        else
            echo "⚠️ Local branch not pushed — $(( $(date +%s) - $(git log -1 --format=%at autonomous/scaffolding) ))s ago"
        fi
    fi
    
    # Check open PRs
    OPEN_PRS=$(gh pr list --repo seleron/agentic-trading-desk --state open 2>/dev/null | wc -l || echo "0")
    if [ "$OPEN_PRS" -gt 0 ]; then
        echo "⚠️ $OPEN_PRS open PR(s) on autonomous/scaffolding:"
        gh pr list --repo seleron/agentic-trading-desk --state open --json number,title,headRefName,statusCheckRollup --jq '.[] | "  #\(.number): \(.title [\(.statusCheckRollup | length checks, pass)] passed)"' 2>/dev/null || true
    else
        echo "✅ No open PRs — loop is clean or hasn't started yet"
    fi
    
    # Check backlog items
    BACKLOG_COUNT=$(ls "$REPO_DIR/backlog/"*.md 2>/dev/null | grep -v README.md | wc -l || echo "0")
    echo ""
    echo "Active backlog items: $BACKLOG_COUNT"
    
    # Reconcile any merged PRs' backlog items (run every health check)
    bash "$REPO_DIR/scripts/hermes/backlog-reconcile.sh" >&2 2>/dev/null || true
fi

echo ""
echo "Done."
