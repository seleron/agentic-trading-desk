---
rank: 5
title: backtest scoring branches are inverted (full scorer never runs)
area: backtest
depends_on: []
---
# Backtest: the full scoring engine never actually runs

## Why
Found during a code-quality review (2026-07-09). In `scripts/backtest.py` the per-bar
scoring branch is inverted:

```python
if i >= 20:
    # simplified SMA-cross composite  ← runs for EVERY bar with history
else:
    # "Full 7-component scoring via indicators + scoring_engine — standalone mode"
    #   ← only runs for i < 20, where closes_hist has < 20 elements → ind = {} →
    #     score_quote gets all-None indicators → degenerate near-zero score
```

So the elaborate `indicators.compute` + `score_quote` path is effectively dead: it
only executes for the first 19 bars, where it is starved of data, while every real
bar uses the simplified SMA/ROC composite. The backtest does NOT exercise the live
scoring engine, so its results don't reflect the strategy the pipeline actually trades.

## Premises & risks
- This is a **strategy-behaviour change**: fixing it will change every backtest metric
  (returns, Sharpe, drawdown, win-rate) and the entry/exit thresholds were tuned to the
  current (simplified) composite. Do NOT just swap the branches — re-tune the
  entry/exit remap and re-validate against real historical bars (see
  `references/composite-remap-thresholds.md`).
- Deterministic tests in `test_pipeline.py` / `test_data_quality.py` pin current backtest
  numbers; they will need updating in lockstep, with the new expected values derived from
  a dry run, not guessed.

## Acceptance
- The backtest scores each bar (with enough history) via the SAME `indicators.compute` +
  `scoring_engine.score_quote` path the live pipeline uses (or an explicitly-documented,
  justified simplification), with the composite normalized consistently.
- Entry/exit thresholds re-tuned and documented; a test asserts the full-scoring path is
  the one taken for bars with sufficient history (e.g. by asserting a bar's composite
  matches `score_quote` output, not the SMA-cross value).
- `bash scripts/ci.sh` prints GATE PASSED; updated deterministic backtest tests pass.

## Constraints
- One concern: this is the backtest scoring path only. Do not touch the live
  orchestrator/scoring numerics in the same PR.

## Notes
- `scripts/backtest.py` ~L171 (`if i >= 20:`) and ~L193 (`else:` labelled "Full … scoring").
- Related low-severity item to fold in or file separately: `calculate_ichimoku` (indicators.py)
  computes Senkou A/B from the latest bars without the standard 26-bar forward shift, so
  `compute_ichimoku_alignment_score` compares price to a non-projected cloud — confirm the
  intended Ichimoku semantics before changing.
