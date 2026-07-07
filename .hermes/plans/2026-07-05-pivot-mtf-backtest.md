# Pivot Levels + Multi-Timeframe + Backtesting Integration Plan

> **For Hermes:** Implement tasks sequentially. Each task is bite-sized (10-15 min max). Commit after each. Verify with smoke test before proceeding.

**Goal:** Wire up the three planned v1.0 features — pivot levels (R2/S2), multi-timeframe verification, and backtesting pipeline integration — into the existing trading desk codebase.

**Architecture:** All modules already exist (`multi_timeframe.py`, `backtest.py`). This task wires them into the orchestrator + scoring engine so they actually run during daily pipeline execution.

**Tech Stack:** Python stdlib only. Existing `scoring_engine.py` (7-component), `orchestrator.py` (pipeline), `multi_timeframe.py` (MTF analysis), `backtest.py` (walk-forward backtest).

---

## Task 1: Add R2/S2 Pivot Levels in Orchestrator

**Objective:** Extend the existing pivot calculation in orchestrator.py to compute R2 and S2 using standard Fibonacci pivot formulas.

**Files:**
- Modify: `scripts/orchestrator.py` lines 115-124

**Current code (lines 115-124):**
```python
        if len(data.get("ohlcv_all", [])) >= 20:
            recent = data["ohlcv_all"][-20:]
            high_20 = max(o["high"] for o in recent)
            low_20 = min(o["low"] for o in recent)
            pivot = (high_20 + low_20 + latest["close"]) / 3
            range_val = high_20 - low_20
            quote["pivot"] = pivot
            quote["r1"] = pivot + range_val * 0.382 if range_val > 0 else None
            quote["s1"] = pivot - range_val * 0.382 if range_val > 0 else None
```

**Step 1: Replace the pivot block with full R1/S1/R2/S2 calculation**

Standard pivot formulas (Fibonacci):
- Pivot = (H + L + C) / 3
- R1 = P + 0.382 × (H - L)
- S1 = P - 0.382 × (H - L)  
- R2 = P + 0.618 × (H - L)
- S2 = P - 0.618 × (H - L)

Replace lines 115-124 with:
```python
        if len(data.get("ohlcv_all", [])) >= 20:
            recent = data["ohlcv_all"][-20:]
            high_20 = max(o["high"] for o in recent)
            low_20 = min(o["low"] for o in recent)
            pivot = (high_20 + low_20 + latest["close"]) / 3
            range_val = high_20 - low_20
            quote["pivot"] = round(pivot, 4) if range_val > 0 else None
            quote["r1"] = round(pivot + range_val * 0.382, 4) if range_val > 0 else None
            quote["s1"] = round(pivot - range_val * 0.382, 4) if range_val > 0 else None
            quote["r2"] = round(pivot + range_val * 0.618, 4) if range_val > 0 else None
            quote["s2"] = round(pivot - range_val * 0.618, 4) if range_val > 0 else None
```

**Step 2: Verify syntax**
Run: `python3 -c "import py_compile; py_compile.compile('scripts/orchestrator.py', doraise=True)"`
Expected: No output (clean compile)

---

## Task 2: Extend Scoring Engine with R2/S2 Pivot Component

**Objective:** Add a pivot_risk_score component that evaluates whether price is safely between S1-R1 or dangerously near support/resistance levels. This gives the scoring engine more nuanced pivot awareness.

**Files:**
- Modify: `scripts/scoring_engine.py` (add new function + integrate into score_quote)

**Step 1: Add compute_pivot_risk_score function after compute_pivot_score**

Add this after line 194 (end of compute_pivot_score):
```python
def compute_pivot_risk_score(
    close: float, pivot: Optional[float], r1: Optional[float], s1: Optional[float],
    r2: Optional[float] = None, s2: Optional[float] = None
) -> tuple[int, list[str]]:
    """Pivot risk scoring — max 5 points.

    Close safely between S1 and R1 (not near edges) → +3
    Close above pivot with room to R2 → +2 continuation signal
    Close below pivot with room to S2 → -0 (neutral bearish)
    Close beyond R1 or below S1 → breakout/breakdown zone (+1 if trending, 0 if not)
    """
    score = 0
    rationale: list[str] = []

    if close > 0 and pivot is not None:
        dist_s1 = abs(close - s1) / close * 100 if s1 else float('inf')
        dist_r1 = abs(close - r1) / close * 100 if r1 else float('inf')

        # Safely between S1 and R1 (not within 3% of edges)
        if s1 is not None and r1 is not None:
            margin = 0.03 * close
            if close > s1 + margin and close < r1 - margin:
                score += 3
                rationale.append("Safely between S1 and R1 — low pivot risk")

        # Above pivot with room to R2 (bullish continuation)
        if close > pivot and r2 is not None and close < r2 - margin:
            score += 2
            rationale.append(f"Above pivot, below R2({r2:.2f}) — bullish continuation zone")

    return min(score, 5), rationale
```

**Step 2: Integrate into COMPONENT_WEIGHTS**

Line 31-39 — add new component (max 5 points to keep total at 105):
Change line 38 from `"technical_summary": 5` to keep it as-is. The total goes from 100 → 105 which is fine since scoring_engine applies `min(100, ...)` on the final score anyway.

**Step 3: Wire into score_quote function**

After line 317 (where compute_pivot_score is called), add a call to compute_pivot_risk_score:
```python
    pivot_risk_score_val, pivot_risk_reasons = compute_pivot_risk_score(
        close, pivot, r1, s1, quote.get("r2"), quote.get("s2")
    )
```

Add `pivot_risk_score_val` to raw_total computation on line 319-320:
Change from:
```python
    raw_total = (trend_score + momentum_score + volume_score_val + ema_struct_score +
                 pivot_score_val + volatility_score_val + tech_summary_score)
```
To:
```python
    raw_total = (trend_score + momentum_score + volume_score_val + ema_struct_score +
                 pivot_score_val + pivot_risk_score_val + volatility_score_val + tech_summary_score)
```

Add `pivot_risk_reasons` to all_reasons on line 327-328:
Change from:
```python
    all_reasons = (trend_reasons + momentum_reasons + volume_reasons + ema_reasons +
                   pivot_reasons + vol_reasons + tech_reasons + penalty_reasons)
```
To:
```python
    all_reasons = (trend_reasons + momentum_reasons + volume_reasons + ema_reasons +
                   pivot_reasons + pivot_risk_reasons + vol_reasons + tech_reasons + penalty_reasons)
```

Add to raw_components dict on line 334-342: Add `"pivot_risk": pivot_risk_score_val` under the existing components.

**Step 4: Verify syntax**
Run: `python3 -c "import py_compile; py_compile.compile('scripts/scoring_engine.py', doraise=True)"`

---

## Task 3: Wire Multi-Timeframe Analysis into Pipeline (Orchestrator)

**Objective:** Call the existing multi_timeframe engine from orchestrator, fetch weekly data alongside daily data, and pass MTF consensus into pipeline output.

**Files:**
- Modify: `scripts/orchestrator.py`

**Step 1: Add multi-timeframe data fetching in run_full_pipeline**

After the indicator computation block (around line 90), add MTF analysis before scoring. We need to fetch weekly closes for each symbol alongside daily closes.

Add after the existing quote-building code (after line 126, before `scores_output = score_quotes(quotes)`):
```python
    # Step 3b: Multi-timeframe verification — fetch weekly data and run MTF analysis
    print("[3/7] Running multi-timeframe verification...")
    import multi_timeframe as mtf_engine

    mtf_consensus = {}
    for symbol, data in ohlcv_data.items():
        if not data.get("ohlcv_all"):
            continue
        daily_closes = [c["close"] for c in data["ohlcv_all"][-250:] if c.get("close")]

        # Fetch weekly closes (need ~104 weeks of data)
        try:
            import yfinance as yf
            wk = yf.Ticker(symbol).history(period="5y", interval="1wk")
            weekly_closes = [c for c in wk["Close"].tolist() if not math.isnan(c)] if "Close" in wk else []
        except Exception:
            weekly_closes = []

        timeframe_scores = {}
        if daily_closes and len(daily_closes) >= 50:
            timeframe_scores["1d"] = daily_closes
        if weekly_closes and len(weekly_closes) >= 50:
            timeframe_scores["1w"] = weekly_closes

        if timeframe_scores:
            mtf_result = mtf_engine.multi_timeframe_analysis(symbol, timeframe_scores)
            mtf_consensus[symbol] = {
                "consensus_score": mtf_result.get("consensus_score", 0),
                "recommendation": mtf_result.get("recommendation", "UNKNOWN"),
                "aligned": mtf_result.get("all_timeframes_aligned", False),
            }

    # Store MTF results per symbol for later use
    for sym in ohlcv_data:
        if sym not in mtf_consensus:
            mtf_consensus[sym] = {"consensus_score": 0, "recommendation": "NO_DATA", "aligned": False}
```

**Step 2: Pass MTF consensus into selection output**

In the pipeline_output dict (around line 188-197), add `mtf_analysis` key:
Add `"mtf_verification": mtf_consensus,` to the pipeline_output dict.

**Step 3: Verify syntax and imports**
Run: `python3 -c "import py_compile; py_compile.compile('scripts/orchestrator.py', doraise=True)"`

---

## Task 4: Upgrade Backtest Engine to Use Full Scoring System

**Objective:** Replace the simplified pillar-based scoring in backtest.py with the real 7-component scoring_engine pipeline. This makes backtests reflect actual trading decisions.

**Files:**
- Modify: `scripts/backtest.py` — replace `run_backtest()` logic (lines ~167-236) to use full scoring engine

**Step 1: Replace simplified pillar scoring with full scoring engine call**

In the `run_backtest()` function, replace lines 172-194 (simplified scoring) with a proper scoring pipeline:
```python
        # Full scoring engine evaluation per bar
        if i >= 200:  # Need enough bars for EMA200 warmup
            recent_closes = [bars[j]["close"] for j in range(max(0, i - 250), i)]

            from score import ScoreResult
            from indicators import compute as compute_indicators

            ind = compute_indicators(recent_closes)
            vol_recent = [bars[j].get("volume", 0) for j in range(i - 20, i) if bars[j].get("volume")]
            volume_avg_20 = sum(vol_recent) / len(vol_recent) if vol_recent else 0

            quote_input = {
                "symbol": self.symbol,
                "date": bars[i].get("date", ""),
                "close": price,
                "open": bars[i].get("open", price),
                "high": bars[i].get("high", price),
                "low": bars[i].get("low", price),
                "volume": bars[i].get("volume", 0),
                "rsi": ind.get("rsi14"),
                "macd": ind.get("macd_line") or 0,
                "macd_signal": ind.get("macd_signal") or 0,
                "ema20": ind.get("ema20"),
                "ema50": ind.get("ema50"),
                "ema200": ind.get("ema200"),
                "volume_avg_20": volume_avg_20,
            }

            # Compute pivot levels for this bar
            if len(recent_closes) >= 20:
                high_recent = max(bars[j]["high"] for j in range(i - 20, i))
                low_recent = min(bars[j]["low"] for j in range(i - 20, i))
                pvt = (high_recent + low_recent + price) / 3
                rng = high_recent - low_recent
                quote_input["pivot"] = round(pvt, 4) if rng > 0 else None
                quote_input["r1"] = round(pvt + rng * 0.382, 4) if rng > 0 else None
                quote_input["s1"] = round(pvt - rng * 0.382, 4) if rng > 0 else None

            # Score using full engine — returns dict with score and rationale
            from scoring_engine import score_quote as sc_engine_score
            scored = sc_engine_score(quote_input)
            composite = scored["score"] / 100.0 * 2 - 1  # Map [0,100] → [-1,+1] for threshold comparison
```

**Step 2: Make run_backtest a method on BacktestResult class (add symbol attribute)**

The current `run_backtest` is a standalone function. To pass `self.symbol`, convert it to use an instance or add a symbol parameter. Simpler approach: keep as function but pass symbol.

Actually, looking at the code more carefully — `run_backtest` doesn't need self. Just change the call site in `main()` to pass bars with proper structure and do scoring inline. Better approach: restructure so that backtest.py imports from scoring_engine directly.

Let me simplify — just import scoring_engine inside run_backtest and use it, passing symbol as a parameter. The cleanest approach is to keep backtest.py standalone but have it call score_quote from scoring_engine internally.

**Revised Step 1:** In `run_backtest()`, replace the simplified scoring block (lines 172-194) with:
```python
        if i >= 200:
            recent_closes = [bars[j]["close"] for j in range(max(0, i - 250), i)]
            import indicators as ind_module
            ind = ind_module.compute(recent_closes)

            vol_recent = [bars[j].get("volume", 0) for j in range(i - 20, i) if bars[j].get("volume")]
            volume_avg_20 = sum(vol_recent) / len(vol_recent) if vol_recent else 0

            quote_input = {
                "symbol": bars[0].get("symbol", "UNKNOWN"),
                "date": bars[i].get("date", ""),
                "close": price,
                "open": bars[i].get("open", price),
                "high": bars[i].get("high", price),
                "low": bars[i].get("low", price),
                "volume": bars[i].get("volume", 0),
                "rsi": ind.get("rsi14"),
                "macd": ind.get("macd_line") or 0,
                "macd_signal": ind.get("macd_signal") or 0,
                "ema20": ind.get("ema20"),
                "ema50": ind.get("ema50"),
                "ema200": ind.get("ema200"),
                "volume_avg_20": volume_avg_20,
            }

            # Compute pivot levels for this bar
            if len(recent_closes) >= 20:
                high_recent = max(bars[j]["high"] for j in range(i - 20, i))
                low_recent = min(bars[j]["low"] for j in range(i - 20, i))
                pvt = (high_recent + low_recent + price) / 3
                rng = high_recent - low_recent
                quote_input["pivot"] = round(pvt, 4) if rng > 0 else None
                quote_input["r1"] = round(pvt + rng * 0.382, 4) if rng > 0 else None
                quote_input["s1"] = round(pvt - rng * 0.382, 4) if rng > 0 else None

            from scoring_engine import score_quote as sc_engine_score
            scored = sc_engine_score(quote_input)
            composite = scored["score"] / 50.0 - 1  # Map [0,100] → [-1,+1], threshold ~0 means score=50
```

Then adjust ENTRY_THRESHOLD to match the new scale: change `ENTRY_THRESHOLD = 0.5` to `ENTRY_THRESHOLD = 0.2` (corresponds to score >= 60).

**Step 3: Update BacktestResult to include scoring stats**

Add fields for tracking how many bars were scored, average score of entries/exits etc. Keep it simple — just add a note about the scoring system used.

**Step 4: Verify syntax**
Run: `python3 -c "import py_compile; py_compile.compile('scripts/backtest.py', doraise=True)"`

---

## Task 5: Add Backtesting Pipeline Step to Orchestrator

**Objective:** Add a dedicated backtesting step in the orchestrator that runs historical analysis for top picks, producing actionable backtest results.

**Files:**
- Modify: `scripts/orchestrator.py` — add backtest step after selection

**Step 1: Add backtest import and execution block**

After line 164 (after trade_plans.json is written), add:
```python
    # Step 7: Backtesting for top picks
    print("[7/8] Running backtests on historical data...")
    from backtest import run_backtest as bt_run, BacktestResult
    import yfinance as yf

    backtest_results = []
    for pick in selection.get("top_picks", []):
        symbol = pick["symbol"]
        try:
            hist = yf.Ticker(symbol).history(period="5y")
            if len(hist) < 200:
                continue
            bars = []
            for _, row in hist.iterrows():
                bars.append({
                    "date": row.name.strftime("%Y-%m-%d"),
                    "open": float(row["Open"]),
                    "high": float(row["High"]),
                    "low": float(row["Low"]),
                    "close": float(row["Close"]),
                    "volume": int(row["Volume"]),
                })

            result = bt_run(
                bars=bars,
                pillar_weights=pillar_weights,
                capital=10000.0,
            )

            backtest_results.append({
                "symbol": symbol,
                "total_return_pct": result.total_return_pct,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown_pct": result.max_drawdown_pct,
                "win_rate_pct": result.win_rate_pct,
                "total_trades": result.total_trades,
            })
        except Exception as e:
            print(f"  [WARN] Backtest failed for {symbol}: {e}", file=sys.stderr)

    with open(os.path.join(output_dir, "backtests.json"), "w") as f:
        json.dump(backtest_results, f, indent=2)
```

**Step 2: Add pillar_weights variable**

Before the backtest block, define `pillar_weights` from config or defaults:
Add after line ~164:
```python
    # Extract pillar weights for backtesting (same as scoring engine weights)
    pillar_weights = {
        "trend": COMPONENT_WEIGHTS.get("trend", 25) / 100,
        "momentum": COMPONENT_WEIGHTS.get("momentum", 20) / 100,
        "macro_sentiment": COMPONENT_WEIGHTS.get("volatility", 10) / 100,
    }
```

Wait — backtest.py expects `pillar_weights` with keys like `"trend"`, `"momentum"`, `"macro_sentiment"` summing to ~1.0. Let me check the exact format needed... The backtest code does:
```python
w_trend = pillar_weights.get("trend", 0.4)
w_mom = pillar_weights.get("momentum", 0.35)
w_macro = pillar_weights.get("macro_sentiment", pillar_weights.get("macro", 0.25))
composite = w_trend * trend_score + w_mom * mom_score + w_macro * macro_score
```

So: `"trend": 0.4, "momentum": 0.35, "macro_sentiment": 0.25` (or "macro" as fallback). The scoring engine weights are 25/20/10/15/10/5 = 85 for trend+momentum+volatility... Let me use reasonable defaults:
```python
    pillar_weights = {
        "trend": 0.4,
        "momentum": 0.35, 
        "macro_sentiment": 0.25,
    }
```

**Step 3: Add backtests to pipeline output**

Add `"backtest_results": backtest_results` to the pipeline_output dict.

**Step 4: Verify syntax and run full orchestrator smoke test**
Run: `python3 -c "import py_compile; py_compile.compile('scripts/orchestrator.py', doraise=True)"`

---

## Task 6: End-to-End Smoke Test on EREGL.IS

**Objective:** Run the full pipeline on EREGL.IS to verify all new features work together.

**Step 1: Run orchestrator with EREGL.IS**
```bash
cd /home/seleron/Desktop/agentic-trading-desk && python3 scripts/orchestrator.py --symbols EREGL.IS --output-dir ./test_outputs/
```

Expected output:
- [1/7] Data collection succeeds
- [2/7] Features + scoring completes  
- [3/7] Multi-timeframe verification runs (weekly data fetched)
- [4/7] Trade plans generated for top picks
- [5/7] Notifications routed
- [6/7] EOD report
- [7/8] Backtests on historical data

**Step 2: Verify output files exist and contain expected keys**
```bash
ls -la ./test_outputs/*.json && echo "---" && python3 -c "
import json
for f in ['scores.json', 'selection.json', 'pipeline_output.json', 'backtests.json']:
    with open(f'test_outputs/{f}') as fh:
        d = json.load(fh)
        print(f'{f}: keys={list(d.keys()) if isinstance(d, dict) else len(d)}')
"
```

**Step 3: Verify MTF consensus is in pipeline output**
Check that `pipeline_output.mtf_verification` contains entries for each scanned symbol with consensus_score and recommendation.

---

## Task 7: Push Branch + Create PR to autonomous/scaffolding

**Objective:** Commit all changes, push branch, create PR targeting autonomous/scaffolding.

```bash
cd /home/seleron/Desktop/agentic-trading-desk
git add scripts/orchestrator.py scripts/scoring_engine.py scripts/backtest.py
git commit -m "feat: wire pivot R2/S2, multi-timeframe verification, and backtesting pipeline

- Add R2/S2 Fibonacci pivot levels to orchestrator
- Extend scoring engine with pivot_risk_score component (max 5pts)
- Wire multi_timeframe.py analysis into daily pipeline (weekly + daily consensus)
- Upgrade backtest.py to use full 7-component scoring_engine instead of simplified pillars
- Add backtesting step to orchestrator for top picks
- Full end-to-end smoke test on EREGL.IS"
git push origin feature/pivot-mtf-backtest-integration
```

Then create PR via gh CLI:
```bash
gh pr create \
  --base autonomous/scaffolding \
  --head feature/pivot-mtf-backtest-integration \
  --title "feat: wire pivot R2/S2, multi-timeframe verification, and backtesting pipeline" \
  --body "$(cat <<'EOF'
## Changes

### Pivot Levels (R1/S1/R2/S2)
- Extended orchestrator to compute full Fibonacci pivot levels including R2/S2
- Added `compute_pivot_risk_score()` to scoring engine — evaluates whether price is safely between S1-R1 or near breakout/breakdown zones (+5 max points)

### Multi-Timeframe Verification  
- Wired existing `multi_timeframe.py` into the daily pipeline via orchestrator
- Fetches weekly data alongside daily for each symbol
- Produces consensus score and recommendation (STRONG BUY / BUY / NEUTRAL / SELL / STRONG SELL)
- MTF results stored in pipeline output under `mtf_verification`

### Backtesting Pipeline Integration
- Upgraded `backtest.py` to use the full 7-component scoring_engine instead of simplified pillar scoring
- Added dedicated backtesting step (step 7/8) in orchestrator that runs 5-year walk-forward backtests on top picks
- Results stored in `backtests.json` with Sharpe, max drawdown, win rate per symbol

### Testing
- End-to-end smoke test: `python3 scripts/orchestrator.py --symbols EREGL.IS --output-dir ./test_outputs/`
- All modules compile cleanly (py_compile)
EOF
)"
```

---

## Verification Checklist

- [x] Task 1: R2/S2 pivot levels in orchestrator — implemented, compiles clean
- [x] Task 2: Pivot risk score in scoring engine — implemented + smoke tested, r2/s2 branch fires correctly (score=5)
- [x] Task 3: MTF wired into pipeline — simplified to `compute_single_tf_score` weekly check via yfinance fallback; full multi-timeframe analysis available separately
- [x] Task 4: Backtest uses scoring_engine fallback (beyond i>=20 warmup); pillar weights still primary path for i<20
- [x] Task 5: Backtesting step in orchestrator — runs on top picks, outputs to `backtest_results` in pipeline output
- [x] Test collection fixed — pytest.ini excludes agentic-trading-review-2/ directory
- [x] Added comprehensive scoring tests (test_scoring_engine.py) exercising r2/s2 continuation branch
- [ ] Task 6: Full smoke test on EREGL.IS — modules import cleanly; full pipeline depends on ccxt/yfinance availability
