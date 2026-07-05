# Address Claude review on PR #2 — resolved (rounds 1–3)
Area: review-fix
Rank: 1
PR: #2
Branch: feature/pivot-mtf-backtest-integration

## Round 1 fixes (committed earlier):
- Fixed failing test gate (EMA structure direction bug: ema200 > ema50 > ema20 → ema20 > ema50 > ema200)
- Populated quote[r2]/[s2] in orchestrator pivot block so compute_pivot_risk_score's +2 continuation branch fires
- Added unit tests for r2/s2 branch coverage
- Deferred MTF (Task 3) and backtest.py upgrade (Tasks 4-5) to separate PRs — this PR focuses on pivot_risk scoring only

## Round 2 fixes:
- Rebalanced weights to sum to 100 (trend 25→22, momentum 20→18) to absorb +5 pivot_risk component

## Round 3 fixes (commit 279b643):
- Dropped dead s2 parameter from compute_pivot_risk_score() — accepted but never used in function body

## Outstanding design note:
- pivot_risk overlaps pivot_position: Both reward the same positional signal (+3 for between S1/R1). Worth deciding if intentional or should be differentiated later.

## Acceptance
All tests pass. Branch updated on origin/feature/pivot-mtf-backtest-integration.

## Constraints
UPDATE the existing branch `feature/pivot-mtf-backtest-integration` (do NOT open a new PR). Do not edit test_data_quality.py.
