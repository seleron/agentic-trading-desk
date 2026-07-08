# Address Claude review on PR #3 — Round 2 fixes
Area: review-fix
Rank: 1
PR: #4

## Required fixes:
- Fix edge case in pivot_risk calculation for low-volume stocks
- Update test assertions for backtest pillar_weights mode

## Status
COMPLETE — `compute_pivot_risk_score` now caps margin at min(0.5×range, 0.25×close) so tight-range / low-volatility stocks can earn safe-zone credit; updated `test_run_backtest_with_pillar_weights` assertions to verify BacktestResult type and sharpe_ratio. All 81 tests pass. Pushed to remote.
