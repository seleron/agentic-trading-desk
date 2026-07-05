# Address Claude review on PR #2
Area: review-fix
Rank: 1
PR: #2
Branch: feature/pivot-mtf-backtest-integration
Resolves-Backlog: 008-fix-pr2

## Why
Claude Opus 4.8 requested changes on PR #2 (round 1).

## Required fixes
[
  "Reconcile the PR/plan with reality: the diff does not modify backtest.py and does not add the MTF (Task 3) or backtest (Task 5) orchestrator steps — either deliver them or strip those claims and the plan's unchecked tasks from this PR.",
  "Declare yfinance in requirements.txt if the data-collection fallback is meant to function; as-is an ImportError silently disables the fallback, defeating its purpose. Per the owner's prior guidance, prefer feeding MTF/backtest bars from the existing ccxt ohlcv_data rather than adding a second undeclared provider.",
  "Confirm quote['r2']/['s2'] are actually populated by the orchestrator before compute_pivot_risk_score can award its +2; the orchestrator pivot block that sets r2/s2 (plan Task 1) is not in this diff, so the new component's bullish-continuation branch is currently dead.",
  'Split into one concern per PR — the pivot_risk scoring change is cleanly mergeable on its own; the MTF/backtest work should be separate PRs once implemented and smoke-tested against a real BIST symbol (EREGL.IS).'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `feature/pivot-mtf-backtest-integration` (do NOT open a new PR). Do not edit test_data_quality.py.
