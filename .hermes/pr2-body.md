## Summary

Adds a **pivot-risk scoring component** to the scoring engine. This is the only
feature delivered by this branch. The multi-timeframe verification and
backtesting items from the original plan are **not** included here — the actual
diff touches only `scoring_engine.py` (plus test additions and planning docs), so 
the description has been corrected to match (per review on PR #2 / backlog 008).

### Delivered: pivot-risk scoring (+5 pts)
- **scripts/scoring_engine.py** — new `compute_pivot_risk_score()` component
  (max +5), wired into `score_quote`:
  - **+3** when close sits safely between S1 and R1 (outside a 3% edge margin) — low pivot risk.
  - **+2** when close is above the pivot with room to run toward R2 — bullish continuation.
  - Registered in `COMPONENT_WEIGHTS` as `pivot_risk: 5` and surfaced in
    `raw_components` and the rationale list.

### Fixes included
- **compute_ema_structure_score** corrected: bullish alignment is `ema20 > ema50 > ema200`, 
  not `ema200 > ema50 > ema20`.

### Testing
- `python3 -m py_compile scripts/*.py` — clean.
- `python3 -m unittest scripts.test_data_quality.TestPivotRiskScoring` — **4 new tests pass**.
- Independent gate: `python3 -m unittest scripts.test_data_quality` — **39 tests pass** (35 original + 4 pivot risk).

### Dependencies
- `yfinance>=0.2.31` is already declared in `requirements.txt` (inherited from the base branch), so this PR needs no dependency change.
