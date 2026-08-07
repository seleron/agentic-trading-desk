---
rank: 0
title: Address Claude review on PR #9
area: review-fix
---
# Address Claude review on PR #9
PR: #9
Branch: auto/daily-validation-tracker
Resolves-Backlog: 027-daily-validation-tracker 007-fix-pr9

## Why
Claude Opus 4.8 requested changes on PR #9 (round 5).

## Required fixes
- Have the morning snapshot ingest the actual pipeline output (read outputs/scores.json / selection.json or accept the orchestrator's scored quotes) instead of re-fetching yfinance and re-scoring via hand-rolled indicators — otherwise validation measures a divergent re-implementation, not the real engine.
- Fix the prediction-correctness semantics in record_eod_actuals to match the engine's real decision bands (BUY≥60 expects up, SELL<40 expects down, HOLD 40–59 should be excluded or graded on a neutral band) rather than a single 60 up/down split that mis-grades every HOLD.
- Remove or fix dead helper `_fetch_score_for_symbol`: it reads `cursor.description` after `conn.close()`, which is unreliable; it is currently unused.
- Avoid the double yfinance fetch + double record_morning_score in the morning CLI path → prepare_morning_snapshot (fetch prices once and pass close_price through).
- Clarify docstring/usage: the today-only hard-guard means this can only accumulate forward from today and cannot 'backtest' historical dates — drop the 'backtesting' framing or state the forward-only constraint.

## Acceptance
- Trusted gate passes: `bash scripts/ci.sh` prints GATE PASSED
- Every fix above is addressed in the diff; no regressions
- Re-review approves

## Constraints
- UPDATE the existing branch `auto/daily-validation-tracker` (do NOT open a new PR)
- Do NOT edit scripts/ci.sh, metrics/baseline.json, or test files to force a pass
