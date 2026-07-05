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
  'Fix the key mismatch in backtest.py:229 — score_quote returns "score" (0–100), not "total_score"; use scored.get("score", 0)/100.0 (and confirm the [0,1] normalization matches ENTRY_THRESHOLD 0.48) so full-engine backtests actually generate trades instead of always returning composite≈0.0048.',
  'Stop re-fetching from yfinance: full history is already in ohlcv_data and the real provider is ccxt via data_fetcher.fetch_bist_data. Feed MTF weekly/daily and the backtest bars from that existing data instead of a second, undeclared provider.',
  'If yfinance is genuinely required, declare it in requirements.txt (it is currently undeclared) rather than relying on runtime try/except swallowing the ImportError.',
  'Add a real end-to-end run (e.g. EREGL.IS) proving MTF consensus populates and backtests.json contains non-zero trades — py_compile alone hides the total_score/zero-trade bug.',
  'Split into one concern per PR: pivot R2/S2, MTF verification, and backtest integration are three separate features.'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `feature/pivot-mtf-backtest-integration` (do NOT open a new PR). Do not edit test_data_quality.py.
