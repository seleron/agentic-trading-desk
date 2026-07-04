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
import os
import sys
from datetime import date as date_type


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
    print("[1/7] Collecting data via ccxt...")
    from scripts.data_fetcher import fetch_bist_data

    symbols = config.get("data", {}).get("symbols", ["EREGL.IS", "TUPRS.IS"])
    exchange_id = config.get("data", {}).get("exchange", "mexc")

    ohlcv_data: dict[str, dict] = {}
    for sym in symbols:
        try:
            raw = fetch_bist_data(sym)
            if not raw or len(raw) < 20:
                print(f"  [WARN] {sym}: insufficient data ({len(raw) if raw else 0} candles)", file=sys.stderr)
                continue
            # Build structured dict for this symbol
            latest = raw[-1] if isinstance(raw[-1], dict) and "c" in raw[-1] else None
            ohlcv_data[sym] = {
                "ohlcv_all": raw,
                "latest": latest,
                "indicators": {},  # populated below by feature engine
            }
        except Exception as e:
            print(f"  [WARN] {sym}: fetch failed ({e})", file=sys.stderr)

    if not ohlcv_data:
        return {"error": "No data collected from ccxt", "symbols_checked": symbols}

    # Step 2 & 3: Feature extraction + Scoring (combined)
    print("[2/7] Computing features and scoring...")
    from scripts.scoring_engine import score_quotes

    quotes = []
    for symbol, data in ohlcv_data.items():
        latest = data["latest"]
        if not latest:
            continue
        quote = {
            "symbol": symbol,
            "date": date_type.today().isoformat(),
            "close": latest["c"],
            "open": latest.get("o", latest["c"]),
            "high": latest.get("h", latest["c"]),
            "low": latest.get("l", latest["c"]),
            "volume": latest.get("v", 0),
            "rsi": data.get("indicators", {}).get("rsi_14"),
            "macd": data.get("indicators", {}).get("macd"),
            "macd_signal": data.get("indicators", {}).get("macdsignal"),
            "ema20": data.get("indicators", {}).get("ema_20"),
            "ema50": data.get("indicators", {}).get("ema_50"),
            "ema200": data.get("indicators", {}).get("ema_200"),
            "volume_avg_20": latest.get("v", 0) * 1.3 if latest.get("v") else 0,
        }

        # Pivot levels (computed from recent H/L)
        if len(data.get("ohlcv_all", [])) >= 20:
            recent = data["ohlcv_all"][-20:]
            high_20 = max(o["h"] for o in recent)
            low_20 = min(o["l"] for o in recent)
            pivot = (high_20 + low_20 + latest["c"]) / 3
            range_val = high_20 - low_20
            quote["pivot"] = pivot
            quote["r1"] = pivot + range_val * 0.382 if range_val > 0 else None
            quote["s1"] = pivot - range_val * 0.382 if range_val > 0 else None

        quotes.append(quote)

    scores_output = score_quotes(quotes)
    with open(os.path.join(output_dir, "scores.json"), "w") as f:
        json.dump(scores_output, f, indent=2)

    # Step 4: Selection (top picks + NO TRADE DAY)
    print("[3/7] Selecting top picks...")
    from scripts.scoring_engine import select_top_picks
    threshold = config.get("scoring", {}).get("threshold", 80)
    selection = select_top_picks(scores_output, threshold=threshold)

    with open(os.path.join(output_dir, "selection.json"), "w") as f:
        json.dump(selection, f, indent=2)

    # Step 5: Trade Plan generation for top picks
    print("[4/7] Generating trade plans...")
    from scripts.trade_plan import generate_trade_plan
    trade_plans = []
    for pick in selection.get("top_picks", []):
        symbol = pick["symbol"]
        if symbol not in ohlcv_data:
            continue
        plan = generate_trade_plan(
            symbol=symbol,
            decision={"signal": "BUY", "score": pick["score"]},
            indicators=ohlcv_data[symbol].get("indicators", {}),
        )
        trade_plans.append(plan)

    with open(os.path.join(output_dir, "trade_plans.json"), "w") as f:
        json.dump(trade_plans, f, indent=2)

    # Step 6: Notification routing
    print("[5/7] Routing notifications...")
    from scripts.notification_router import route_notifications
    all_scores = scores_output if isinstance(scores_output, list) else [scores_output]
    notifications = route_notifications(all_scores, selection)

    with open(os.path.join(output_dir, "notifications.json"), "w") as f:
        json.dump(notifications, f, indent=2)

    # Step 7: EOD report (if we have existing trades in DB)
    print("[6/7] Generating EOD report...")
    from scripts.eod_module import generate_eod_report
    db_path = config.get("eod", {}).get("db_path", "data/trades.db")
    eod_report = generate_eod_report(db_path, date_type.today().isoformat())

    # Step 8: Learning module check (every run)
    print("[7/7] Checking learning module...")
    from scripts.learning_module import analyze_trades
    min_trades = config.get("learning", {}).get("min_trades", 50)
    learning_result = analyze_trades(db_path, min_trades=min_trades)

    # Final assembly
    pipeline_output = {
        "date": date_type.today().isoformat(),
        "exchange": exchange_id,
        "symbols_scanned": len(quotes),
        "selection": selection,
        "trade_plans": trade_plans,
        "notifications_count": len(notifications),
        "eod_report": eod_report if not eod_report.get("no_trades") else None,
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
        config["data"]["symbols"] = args.symbols

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
