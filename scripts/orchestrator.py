#!/usr/bin/env python3
"""
orchestrator.py
===============
Main orchestrator for BIST AI Trader v1.0.

Chains all modules per spec architecture:
  Data Collector → Feature Engine → Scoring Engine → Selection Engine
    → Trade Plan Generator → Notification Router → EOD Module → Learning Module

Usage:
    python3 scripts/orchestrator.py --symbols EREGL.IS TUPRS.IS --output-dir ./outputs/
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from datetime import date as date_type

# Allow both `python3 scripts/orchestrator.py` (scripts/ on sys.path) and
# `python3 -m scripts.orchestrator`: ensure this dir is importable as flat modules.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def load_config(config_path: str = "config.yaml") -> dict:
    """Load configuration."""
    try:
        import yaml
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except ImportError:
        # Minimal fallback if PyYAML not installed
        return {
            "scoring": {"threshold": 80, "top_n": 2},
            "data": {"exchange": "XISL", "symbols_file": None},
            "eod": {"db_path": "data/trades.db"},
            "learning": {"min_trades": 50},
        }


def run_full_pipeline(config: dict, output_dir: str) -> dict:
    """Run the full pipeline end-to-end."""
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Data Collection (via ccxt)
    print("[1/9] Collecting data via ccxt...")
    from data_fetcher import fetch_bist_data

    symbols = config.get("data", {}).get("symbols", ["EREGL.IS", "TUPRS.IS"])
    exchange_id = config.get("data", {}).get("exchange", "mexc")

    ohlcv_data: dict[str, dict] = {}
    for sym in symbols:
        try:
            raw = fetch_bist_data(sym)
            if not raw or len(raw) < 20:
                # Fallback to yfinance when ccxt lacks the symbol
                import yfinance as _yf  # noqa: F811 — local block only
                hist_yf = _yf.Ticker(sym).history(period="5y")
                if len(hist_yf) < 20:
                    print(f"  [WARN] {sym}: insufficient data ({len(raw) if raw else 0} candles)", file=sys.stderr)
                    continue
                # Convert yfinance OHLCV to ccxt-compatible dict format
                raw = []
                for _, row in hist_yf.iterrows():
                    dt_str = row.name.strftime("%Y-%m-%d")
                    raw.append({
                        "date": dt_str,
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row["Volume"]) if not math.isnan(row["Volume"]) else 0,
                    })
                print(f"  [INFO] {sym}: fetched via yfinance ({len(raw)} bars)", file=sys.stderr)
            # Build structured dict for this symbol
            latest = raw[-1] if isinstance(raw[-1], dict) and "close" in raw[-1] else None
        except Exception as e:
            print(f"  [WARN] {sym}: ccxt fetch failed ({e})", file=sys.stderr)
            # Try yfinance fallback when ccxt raises an exception
            try:
                import yfinance as _yf  # noqa: F811 — local block only
                hist_yf = _yf.Ticker(sym).history(period="5y")
                if len(hist_yf) >= 20:
                    raw = []
                    for _, row in hist_yf.iterrows():
                        dt_str = row.name.strftime("%Y-%m-%d")
                        raw.append({
                            "date": dt_str,
                            "open": float(row["Open"]),
                            "high": float(row["High"]),
                            "low": float(row["Low"]),
                            "close": float(row["Close"]),
                            "volume": int(row["Volume"]) if not math.isnan(row["Volume"]) else 0,
                        })
                    print(f"  [INFO] {sym}: fetched via yfinance ({len(raw)} bars)", file=sys.stderr)
                else:
                    raw = []
            except Exception as e2:
                raw = []

        if not raw or len(raw) < 20:
                print(f"  [WARN] {sym}: insufficient data ({len(raw) if raw else 0} bars)", file=sys.stderr)
                continue

        # Build structured dict for this symbol (after successful fetch from either source)
        latest = raw[-1] if isinstance(raw[-1], dict) and "close" in raw[-1] else None
        ohlcv_data[sym] = {
            "ohlcv_all": raw,
            "latest": latest,
            "indicators": {},  # populated below by feature engine
        }

    if not ohlcv_data:
        return {"error": "No data collected from ccxt", "symbols_checked": symbols}

    # Load admin corrections before scoring (so overrides apply to computed scores)
    print("[1.5/9] Loading admin corrections...")
    try:
        from admin_corrections import load_corrections_from_config, is_ignored as _is_ignored
        admin_corrections = load_corrections_from_config(config or {})
        # Filter out ignored symbols early
        ohlcv_data = {k: v for k, v in ohlcv_data.items() if not _is_ignored(k, admin_corrections)}
    except Exception as e:
        print(f"  [WARN] Admin corrections load failed ({e}), continuing without overrides", file=sys.stderr)
        admin_corrections = {}

    print("[2/9] Computing features and scoring...")
    from scoring_engine import score_quotes
    import indicators as indicators_engine

    quotes = []
    for symbol, data in ohlcv_data.items():
        latest = data["latest"]
        if not latest:
            continue

        # --- Feature engine: deterministic indicator stack from the close series ---
        closes = [c["close"] for c in data["ohlcv_all"] if c.get("close") is not None]
        highs = [c["high"] for c in data["ohlcv_all"] if c.get("high") is not None]
        lows = [c["low"] for c in data["ohlcv_all"] if c.get("low") is not None]
        vols = [c.get("volume", 1) or 1 for c in data["ohlcv_all"]]

        ind = indicators_engine.compute(
            closes, highs=highs, lows=lows, volumes=vols
        ) if len(closes) >= 20 else {}
        data["indicators"] = ind

        # Real 20-bar average volume (falls back to current volume if unavailable).
        recent_vols = [c.get("volume") for c in data["ohlcv_all"][-20:] if c.get("volume")]
        volume_avg_20 = (sum(recent_vols) / len(recent_vols)) if recent_vols else 0

        quote = {
            "symbol": symbol,
            "date": date_type.today().isoformat(),
            "close": latest["close"],
            "open": latest.get("open", latest["close"]),
            "high": latest.get("high", latest["close"]),
            "low": latest.get("low", latest["close"]),
            "volume": latest.get("volume", 0),
            "rsi": ind.get("rsi14"),
            # scoring_engine guards rsi/ema for None but treats macd as numeric;
            # default to 0 (neutral) when warmup leaves the MACD line undefined.
            "macd": ind.get("macd_line") or 0,
            "macd_signal": ind.get("macd_signal") or 0,
            "ema20": ind.get("ema20"),
            "ema50": ind.get("ema50"),
            "ema200": ind.get("ema200"),
            "volume_avg_20": volume_avg_20,
        }

         # Pivot levels (Fibonacci: P, R1/S1, R2/S2)
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

        # Pass ichimoku data to scoring engine for alignment component
        quote["_ichimoku"] = ind.get("ichimoku")

        quotes.append(quote)

    scores_output = score_quotes(quotes, admin_corrections=admin_corrections)
    with open(os.path.join(output_dir, "scores.json"), "w") as f:
        json.dump(scores_output, f, indent=2)

    # Step 4b: Multi-timeframe verification — weekly trend confirmation for daily signals
    print("[3/9] Running multi-timeframe analysis...")
    from multi_timeframe import compute_single_tf_score

    mtf_consensus = {}
    for quote in quotes:
        symbol = quote["symbol"]
        data = ohlcv_data.get(symbol, {})
        closes_daily = [c["close"] for c in data.get("ohlcv_all", []) if c.get("close")]

        # Fetch weekly data for multi-timeframe verification (via yfinance fallback)
        try:
            import yfinance as _yf  # noqa: F811 — local to this block only
            hist_wk = _yf.Ticker(symbol).history(period="5y", interval="1wk")
            closes_weekly = [float(c) for c in hist_wk["Close"] if not math.isnan(c)] if len(hist_wk) > 0 else []
        except Exception:
            # If yfinance fails, use daily data as proxy (single-timeframe fallback)
            closes_weekly = closes_daily

        weekly_score = compute_single_tf_score(closes_weekly) if closes_weekly else {"score": 0}
        mtf_consensus[symbol] = {
            "weekly_trend_score": weekly_score.get("score", 0),
            "daily_bullish": quote.get("close", 0) > (quote.get("ema20") or 0),
            "weekly_bullish": weekly_score.get("score", 0) >= 5,
        }

    # Save MTF results for pipeline output
    print("[4/9] Selecting top picks...")
    from scoring_engine import select_top_picks
    threshold = config.get("scoring", {}).get("threshold", 80)
    selection = select_top_picks(scores_output, threshold=threshold)

    with open(os.path.join(output_dir, "selection.json"), "w") as f:
        json.dump(selection, f, indent=2)

    # Step 5: Trade Plan generation for top picks
    print("[5/9] Generating trade plans...")
    from trade_plan import generate_trade_plan
    trade_plans = []
    for pick in selection.get("top_picks", []):
        symbol = pick["symbol"]
        if symbol not in ohlcv_data:
            continue
        plan = generate_trade_plan(
            symbol=symbol,
            # trade_plan detects long entries by keyword in `action` ("RE-ENTRY" /
            # "TACTICAL REBOUND"); a top-pick BUY maps to RE-ENTRY so a real plan
            # is produced instead of a no_trade stub.
            decision={
                "action": "RE-ENTRY",
                "score": pick["score"],
                "rationale": "; ".join(pick.get("rationale", [])),
            },
            indicators=ohlcv_data[symbol].get("indicators", {}),
        )
        trade_plans.append(plan)

    with open(os.path.join(output_dir, "trade_plans.json"), "w") as f:
        json.dump(trade_plans, f, indent=2)

    # Step 6: Notification routing
    print("[6/9] Routing notifications...")
    from notification_router import route_notifications
    all_scores = scores_output if isinstance(scores_output, list) else [scores_output]
    notifications = route_notifications(all_scores, selection)

    with open(os.path.join(output_dir, "notifications.json"), "w") as f:
        json.dump(notifications, f, indent=2)

    # Step 7: EOD report (if we have existing trades in DB)
    print("[7/9] Generating EOD report...")
    from eod_module import generate_eod_report
    db_path = config.get("eod", {}).get("db_path", "data/trades.db")
    eod_report = generate_eod_report(db_path, date_type.today().isoformat())

    # Step 8: Learning module check (every run)
    print("[8/9] Checking learning module...")
    from learning_module import analyze_trades
    min_trades = config.get("learning", {}).get("min_trades", 50)
    learning_result = analyze_trades(db_path, min_trades=min_trades)

    # Step 7b: Backtesting for top picks — run historical walk-forward on selected symbols
    print("[9/9] Running backtests on historical data...")
    from backtest import run_backtest as bt_run, BacktestResult

    backtest_results = []

    for pick in selection.get("top_picks", []):
        symbol = pick["symbol"]
        try:
            # Try ccxt first (same source as live pipeline), fall back to yfinance
            hist_raw = None
            try:
                hist_raw = fetch_bist_data(symbol, timeframe="1d", limit=450)
            except Exception:
                pass  # ccxt fallback below

            if not hist_raw or len(hist_raw) < 200:
                # Fallback to yfinance for BIST symbols (ccxt lacks many Turkish stocks)
                import yfinance as _yf  # noqa: F811 — local to this block only

                hist_yf = _yf.Ticker(symbol).history(period="5y")
                if len(hist_yf) < 200:
                    print(f"  [WARN] Backtest: insufficient history for {symbol}", file=sys.stderr)
                    continue
                bars = []
                for _, row in hist_yf.iterrows():
                    bars.append({
                        "date": row.name.strftime("%Y-%m-%d"),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row["Volume"]) if not math.isnan(row["Volume"]) else 0,
                    })
            else:
                bars = []
                for bar in hist_raw[:350]:  # cap at ~350 bars to keep runtime reasonable
                    bars.append({
                        "date": bar.get("date", ""),
                        "open": float(bar["open"]),
                        "high": float(bar["high"]),
                        "low": float(bar["low"]),
                        "close": float(bar["close"]),
                        "volume": int(bar.get("volume", 0)),
                    })

            # Backtest pillar weights come from config (fall back to sensible
            # defaults matching run_backtest's expected keys).
            bt_weights = config.get("backtest", {}).get(
                "pillar_weights",
                {"trend": 0.4, "momentum": 0.3, "macro_sentiment": 0.3},
            )
            result = bt_run(
                bars=bars,
                pillar_weights=bt_weights,
                capital=10000.0,
            )

            backtest_results.append({
                "symbol": symbol,
                "total_return_pct": round(result.total_return_pct, 2),
                "sharpe_ratio": round(result.sharpe_ratio, 4) if result.sharpe_ratio is not None else None,
                "max_drawdown_pct": round(result.max_drawdown_pct, 2),
                "win_rate_pct": round(result.win_rate_pct, 2),
                "total_trades": result.total_trades,
            })
        except Exception as e:
            print(f"  [WARN] Backtest failed for {symbol}: {e}", file=sys.stderr)

    pipeline_output = {
        "date": date_type.today().isoformat(),
        "exchange": exchange_id,
        "symbols_scanned": len(quotes),
        "selection": selection,
        "trade_plans": trade_plans,
        "notifications_count": len(notifications),
        "eod_report": eod_report if not eod_report.get("no_trades") else None,
        "mtf_verification": mtf_consensus,
        "backtest_results": backtest_results,
        "learning_ready": learning_result.get("ready", False),
    }

    with open(os.path.join(output_dir, "pipeline_output.json"), "w") as f:
        json.dump(pipeline_output, f, indent=2)

    return pipeline_output


def main() -> int:
    ap = argparse.ArgumentParser(description="BIST AI Trader v1.0 — Full Pipeline Orchestrator.")
    ap.add_argument("--config", "-c", default="config.yaml", help="Config file path")
    ap.add_argument("--output-dir", "-o", default="./outputs/", help="Output directory for results")
    ap.add_argument("--symbols", nargs="+", default=None, help="Override symbols from config")
    args = ap.parse_args()

    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"[ERROR] Failed to load config: {e}", file=sys.stderr)
        return 1

    if args.symbols:
        config.setdefault("data", {})["symbols"] = args.symbols

    result = run_full_pipeline(config, args.output_dir)

    # Print summary
    print("\n" + "=" * 60, file=sys.stderr)
    print(f"[PIPELINE COMPLETE] {date_type.today().isoformat()}", file=sys.stderr)
    if "error" in result:
        print(f"  ERROR: {result['error']}", file=sys.stderr)
    else:
        selection = result.get("selection", {})
        print(f"  Symbols scanned: {result['symbols_scanned']}", file=sys.stderr)
        print(f"  Market bias:     {selection.get('market_bias', 'N/A')}", file=sys.stderr)
        print(f"  Top picks:       {len(selection.get('top_picks', []))}", file=sys.stderr)
        for pick in selection.get("top_picks", []):
            print(f"    → {pick['symbol']} (score={pick['score']})", file=sys.stderr)
        if selection.get("no_trade_day"):
            print("  ** NO TRADE DAY **", file=sys.stderr)
        print("=" * 60, file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
