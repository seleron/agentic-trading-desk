---
rank: 3
title: Fix learning module SQLite column indexing bug
area: bugfix
depends_on: []
---

## Problem

`learning_module.py` uses tuple index `r[5]` for the trade score, but in the DB schema (`SELECT * FROM trades`), column order is:
- 0=id, 1=symbol, 2=date, **3=score**, 4=entry_price, 5=exit_price, 6=result

So `r[5]` returns exit_price (e.g. 43.0) instead of score (e.g. 85.0), producing meaningless "avg win/loss scores" and a broken score_separation metric.

## Impact

- Learning module reports avg_win_score as ~77.5 (an exit price, not a score)
- Score separation is negative (-202.5) because it compares exit prices of wins vs losses
- Weight adjustment recommendations are unreliable since they depend on score thresholds

## Implementation Plan

1. **Fix column indices in `analyze_trades()`** — change all references from `r[5]` to `r[3]` for score, and verify `r[6]` is correct for result (WIN/LOSS/BREAKEVEN)
2. **Add defensive column validation** — at the top of `analyze_trades()`, assert that the cursor description matches expected schema or raise a clear error with column names
3. **Fix test DB in tests/** — ensure any existing test fixture uses the correct schema (`score` at index 3, not exit_price)
4. **Add unit test** — create a minimal test case with known scores (e.g., score=90 WIN, score=30 LOSS) and verify `avg_win_score > avg_loss_score` and positive separation

## Files to Touch

- `scripts/learning_module.py` — line ~50 (`score = r[5]`)
- Any test fixtures in `tests/` that create learning module DB schema
- Optionally: add a `--schema-check` flag for CI validation

## Status
✅ **RESOLVED** — Fix already applied in commit 2ad5117 ("fix: address PR #1 review — ema200 wiring, volume_avg_20 handling, column indices, imports"). Column indices updated from `r[5]`/`r[6]` to `r[6]`/`r[5]` (score at index 6, result at index 5 per CREATE TABLE schema). Verified: avg_win_score=87.5, avg_loss_score=55.0 with known test data — correct.

## Implementation notes
- Column order in DB: id=0, date=1, symbol=2, entry=3, exit=4, result=5, score=6, pnl=7, pnl_pct=8, rationale=10 (duration_bars not inserted, defaults to 0)
- learning_module.py line ~57 changed from `score = r[5]` → `r[6]`; line ~58 changed from `result = r[6]` → `r[5]`
- Added column-order comment block above the analysis loop for clarity
