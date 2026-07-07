---
rank: 7
title: relative-strength-vs-bist50
area: analysis_enhancement
depends_on: []
---

## Why

None of the comparable projects (RyanJHamby/stock-screener, ti_numba, borsapy) explicitly rank stocks by their **relative strength vs. a benchmark** — this is one of the most common filters used in professional scanners. stock-screener uses Mark Minervini's RS-Rank concept (price performance relative to all US stocks), but our project scores each stock absolutely without any cross-stock normalization.

For BIST specifically, this matters because:
- Turkish markets are heavily driven by macro flows and sector rotation — a stock that looks "strong" in absolute terms may actually be lagging the broader market
- The existing `select_top_picks()` function sorts by raw score only; two stocks with identical 78-point scores could have vastly different relative performance vs. BIST50

Projects like **stock-screener** filter for Stage 2 uptrends where price beats a moving average AND beats the broader market — ours has no such cross-asset comparison at all. Adding a Relative Strength (RS) component would let us distinguish "strong in a weak market" from "weak in a strong market."

## Acceptance Criteria
- [ ] `scoring_engine.py` accepts an optional `benchmark_closes` list and computes a **relative strength ratio** (stock close / benchmark close over a configurable lookback window, default 20 days)
- [ ] The RS ratio is mapped to a **+1/-1 modifier** on the existing score: if stock outperforms benchmark by ≥ threshold → +1; underperforms by ≥ threshold → -1; otherwise neutral. Threshold configurable in `config.yaml` (`scoring.rs_threshold`).
- [ ] A new CLI flag `--benchmark-symbol BIST50` on `orchestrator.py` that fetches the BIST50 index series (via yfinance: `^BIST` or ccxt if available) and passes closes to all scoring calls.
- [ ] Pipeline output in `pipeline_output.json` includes a new field `"relative_strength"` per stock with ratio, direction, and whether it was adjusted.
- [ ] Unit test verifying RS modifier logic with synthetic data (stock up 10%, benchmark up 5% → +1; stock down 3%, benchmark up 8% → -1).

## Constraints
- Must not change the existing 0–100 scoring scale or component weights. The RS modifier is a post-hoc adjustment, not a new component.
- Benchmark data fetch must use the same ccxt/yfinance fallback pattern as existing code — no new hard dependencies.
- Default threshold: 5% relative outperformance for +1, -5% for -1 (configurable).

## Notes
- The RS ratio computation is mathematically simple: `ratio = stock_close_n / stock_close_0 / (benchmark_close_n / benchmark_close_0)` which equals `(stock_return) / (benchmark_return)`.
- Reference: Minervini's RS-Rank ranks stocks by 26-week return percentile — we're doing a simpler but sufficient version.
- Consider adding **sector-relative strength** later if BIST sector data becomes available via borsapy or yfinance (`BIST100_TEKNO`, `BIST100_ENERJI`, etc.).
