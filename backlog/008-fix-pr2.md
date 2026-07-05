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
  "Do not re-fetch data from yfinance: the pipeline's real source is ccxt via fetch_bist_data, and full history is already in `ohlcv_data`. Feed MTF weekly/daily and the backtest bars from that existing data (or from data_fetcher) instead of a second, undeclared provider.",
  'If yfinance must be used, add it to requirements.txt AND wrap the `import yfinance as yf` in the backtest block (line ~230) in try/except so an ImportError degrades gracefully (skip backtests) rather than crashing the whole pipeline after all prior steps succeeded.',
  "Reconcile the PR description with reality: backtest.py is unchanged, so the claim 'Upgraded backtest.py to use the full 7-component scoring_engine' is false — either implement plan Task 4 or remove that claim.",
  "Confirm the MTF/backtest steps actually run end-to-end against a real BIST symbol (e.g. EREGL.IS) rather than only py_compile; the plan's Task 6 smoke test is unchecked.",
  'Split into one concern per PR (pivot R2/S2, MTF, backtest integration are three distinct features).'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `feature/pivot-mtf-backtest-integration` (do NOT open a new PR). Do not edit test_data_quality.py.
