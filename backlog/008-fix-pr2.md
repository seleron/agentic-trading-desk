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
  'Fix the failing independent gate: run the restored unittest suite locally, identify the failing test, and fix the code (do NOT weaken or delete the test to make it pass). The PR cannot merge while the gate is red.',
  'Declare yfinance in requirements.txt — both the orchestrator fetch-fallback and the planned MTF/backtest steps import it, but it is currently undeclared so the runtime try/except silently swallows ImportError and disables the fallback. Per prior owner guidance, prefer feeding MTF/backtest bars from the existing ccxt ohlcv_data rather than adding a second undeclared provider.',
  'Reconcile the PR with reality: the diff does not modify backtest.py and does not add the MTF (Task 3) or backtest (Task 5) orchestrator steps, yet the plan/description claim them. Either deliver those steps in this PR or strip the claims and unchecked plan tasks.',
  "Confirm the orchestrator actually populates quote['r2']/['s2'] before compute_pivot_risk_score runs — the Task 1 pivot block that sets r2/s2 is not in this diff, so the new +2 bullish-continuation branch is currently dead code in production.",
  'Split into one concern per PR: the pivot_risk scoring change is cleanly mergeable alone; MTF and backtest wiring should be separate PRs, each smoke-tested end-to-end against a real BIST symbol (e.g. EREGL.IS) proving non-zero results.'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `feature/pivot-mtf-backtest-integration` (do NOT open a new PR). Do not edit test_data_quality.py.
