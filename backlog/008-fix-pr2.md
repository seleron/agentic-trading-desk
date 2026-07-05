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
  'Declare yfinance in requirements.txt — the data-collection fallback is wrapped in try/except ImportError, so without the dependency installed it silently returns raw=[] and the fallback never actually runs, making it dead code in production.',
  'Reconcile the PR description/plan with the diff: only pivot_risk scoring + the yfinance data-collection fallback are delivered. MTF wiring into the orchestrator and the backtest.py full-engine upgrade (plan Tasks 3-5) are absent — remove those claims or deliver them.',
  "Confirm the orchestrator actually populates quote['r2']/['s2'] (base commit bdc1020) so compute_pivot_risk_score's +2 'below R2' branch can fire; otherwise pivot_risk caps at 3/5 in practice — add or point to a scoring test that exercises the r2 branch.",
  'Split into one concern per PR: pivot_risk scoring and the data-source fallback are two distinct changes.'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `feature/pivot-mtf-backtest-integration` (do NOT open a new PR). Do not edit test_data_quality.py.
