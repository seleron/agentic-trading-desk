---
rank: 3
title: relative-strength-vs-bist50
area: scoring
depends_on: []
---
# Relative strength vs BIST50 benchmark modifier

## Why

None of the comparable projects (stock-screener, ti_numba, borsapy) rank stocks by
**relative strength vs. a benchmark** — a staple of professional scanners. We score each
stock absolutely with no cross-stock/market normalization. For BIST this matters: Turkish
markets are macro/sector-flow driven, so a stock "strong" in absolute terms may be lagging
the market. `select_top_picks()` sorts by raw score only — two 78-point stocks can have very
different performance vs. BIST50. An RS modifier distinguishes "strong in a weak market" from
"weak in a strong market."

## Prior attempt (PR #6) — the bug to NOT repeat
A previous branch implemented this but the +1/-1 modifier was a **no-op**: `score_quote`
computed `final_score = max(0, min(100, original_score + rs_info['direction']))` inside the RS
block, then an **unconditional** `final_score = max(0, min(100, raw_total + penalties))`
immediately overwrote it. The feature looked done but never changed the score, and the test
only asserted `score` was an int so it didn't catch it. Do not reproduce this.

## Acceptance
- `scoring_engine.py` accepts an optional `benchmark_closes` list and computes a relative
  strength ratio (stock return / benchmark return over a configurable lookback, default 20).
- The ratio maps to a **+1/-1 modifier** actually applied to the final score: outperform by
  ≥ `scoring.rs_threshold` (config) → +1; underperform by ≥ threshold → -1; else neutral.
  There must be exactly ONE final_score assignment path — the RS modifier must survive to the
  returned value (no later unconditional overwrite).
- `orchestrator.py` gets a `--benchmark-symbol` flag that fetches the benchmark series via the
  existing yfinance/ccxt fallback and passes closes to scoring.
- `pipeline_output.json` includes a per-stock `relative_strength` field (ratio, direction,
  adjusted?).
- **Test that asserts the NUMERIC effect**, not just the type: e.g. a quote scoring N with an
  outperforming benchmark returns N+1 (clamped), and N-1 when underperforming. This test must
  fail if the modifier is a no-op.
- Gate passes: `bash scripts/ci.sh` prints GATE PASSED; bump `metrics/baseline.json:minTests`
  for the new test(s).

## Constraints
- Do NOT change the 0–100 scale or component weights — the RS modifier is a post-hoc ±1, not a
  new component.
- Benchmark fetch uses the existing yfinance/ccxt fallback — no new hard dependencies.
- config: `scoring.rs_threshold` (default 0.05 = 5%).

## Notes
- ratio = (stock_close_n / stock_close_0) / (benchmark_close_n / benchmark_close_0).
- Reference: Minervini RS-Rank (26-week return percentile) — we do a simpler sufficient version.
