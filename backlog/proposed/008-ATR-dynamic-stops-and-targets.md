---
rank: 8
title: ATR-based-dynamic-stops-and-targets
area: risk_management
depends_on: []
---

## Why

Our `trade_plan.py` generates entry/stop/target levels, but the stop-loss is currently a **fixed percentage** below entry. This is one of the biggest gaps compared to all comparable projects:

- **ti_numba** (the leading Python indicator library) includes ATR as a core indicator, and most quant scanners use ATR × multiplier for stops because it adapts to current volatility
- **stock-screener** uses fixed stop losses but explicitly documents that ATR-based stops would be a "v2" improvement
- The existing `scoring_engine.py` has a "Volatility" component (max 10 pts) based on a simple `(high - low) / close` ratio, but this is **not the same as ATR** and isn't used for position management

For BIST stocks specifically, volatility regimes change dramatically:
- Low-float names can swing 8–12% daily; large-caps like EREGL typically move 1–3%. A fixed 5% stop would get stopped out of normal noise on volatile names but be too wide for stable ones.
- The Turkish market has circuit breakers (±10%) and a T+1 settlement — stops need to account for gap risk between sessions.

## Acceptance Criteria
- [ ] `indicators.py` gains an `compute_atr(high_series, low_series, close_series, period=14)` function that returns the Wilder-smoothed True Range average (matching the existing RSI/TRIX implementation style).
- [ ] `trade_plan.py` accepts a new config option `stop_loss_method: "fixed_pct" | "atr"` (default `"fixed_pct"` for backward compatibility). When `"atr"`, stop loss = `entry - (ATR × multiplier)`. Multiplier configurable in `config.yaml` under `scoring.stop_atr_multiplier` (default 2.0).
- [ ] Take-profit targets also become ATR-aware: TP1 = entry + (ATR × 1.5), TP2 = entry + (ATR × 3.0) — following a standard risk-reward framework (1:1.5, 1:3).
- [ ] `trade_plan.py` output JSON includes `"stop_loss_method"` and `"atr_value"` fields so the orchestrator can report this to the user.
- [ ] Backtest engine (`backtest.py`) uses ATR stops when enabled — verified with a synthetic backtest that produces different results from fixed-pct mode.

## Constraints
- Must remain backward compatible: if `stop_loss_method` is not set in config, use existing fixed-percentage behavior.
- ATR computation must match Wilder's smoothing (same method as RSI in the codebase) — not a simple SMA of True Range.
- No new external dependencies; ATR uses only high/low/close arrays already available from `indicators.py`.

## Notes
- Reference: Welles Wilder's original ATR definition (from "New Concepts in Technical Trading Systems"). The True Range at time t is `max(H-t - Lt, abs(H-t - C(t-1)), abs(Lt - C(t-1)))`, smoothed with a 14-period EMA-style average.
- For BIST, consider adding an optional **gap fill buffer**: if the previous day's low/high created a gap today, widen the stop by half the gap size to avoid premature exits.
