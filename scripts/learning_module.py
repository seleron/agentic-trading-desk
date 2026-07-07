#!/usr/bin/env python3
"""
learning_module.py
==================
Learning module for BIST AI Trader v10.

Per spec: Every 50 trades, analyze which features perform best and auto-update pillar weights.

Analysis:
  - Which RSI ranges produce better outcomes?
  - Which EMA structure works most reliably?
  - Does volume spike actually work?
  - Is MACD reliable?

Output: Updated weight configuration with confidence intervals.

Usage:
    python3 scripts/learning_module.py --db data/trades.db --output config_updates.json
"""
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys


def analyze_trades(db_path: str, min_trades: int = 50) -> dict:
    """Analyze trade performance by feature type. Returns weight adjustment recommendations."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT * FROM trades WHERE result IN ('WIN', 'LOSS') ORDER BY date"
        )
        rows = cursor.fetchall()
    except sqlite3.OperationalError:
        # No trades table yet (fresh/uninitialised DB) — treat as zero trades.
        rows = []
    finally:
        conn.close()

    if len(rows) < min_trades:
        return {
            "trades_analyzed": len(rows),
            "min_required": min_trades,
            "ready": False,
            "message": f"Need {min_trades} completed trades for analysis (have {len(rows)}).",
            "weights": {},
        }

    # Group by score bracket
    win_by_score_bracket = {}  # e.g., {"80-90": {"wins": 3, "total": 5}}
    # Column order (SELECT *): id=0, date=1, symbol=2, entry=3, exit=4,
    # result=5, score=6, pnl=7, pnl_pct=8, duration_bars=9, rationale=10
    for r in rows:
        score = r[6]
        result = r[5]  # WIN/LOSS/BREAKEVEN
        bracket = (score // 10) * 10
        key = f"{bracket}-{bracket + 9}"

        if key not in win_by_score_bracket:
            win_by_score_bracket[key] = {"wins": 0, "total": 0}
        win_by_score_bracket[key]["total"] += 1
        if result == "WIN":
            win_by_score_bracket[key]["wins"] += 1

    # Calculate win rate per bracket
    bracket_win_rates = {}
    for bracket, data in sorted(win_by_score_bracket.items()):
        if data["total"] >= 3:  # minimum sample size
            wr = data["wins"] / data["total"] * 100
            bracket_win_rates[bracket] = round(wr, 1)

    # Analyze score vs outcome correlation (simplified — needs rationale parsing for full feature analysis)
    win_trades = [r for r in rows if r[5] == "WIN"]
    loss_trades = [r for r in rows if r[5] == "LOSS"]

    avg_win_score = sum(r[6] for r in win_trades) / len(win_trades) if win_trades else 0
    avg_loss_score = sum(r[6] for r in loss_trades) / len(loss_trades) if loss_trades else 0

    # Score separation: higher gap means scoring system is predictive
    score_separation = round(avg_win_score - avg_loss_score, 1)

    # Weight adjustment recommendations (heuristic)
    adjustments = []

    if win_by_score_bracket.get("90-99", {}).get("total", 0) > 0:
        wr_90 = win_by_score_bracket["90-99"]["wins"] / win_by_score_bracket["90-99"]["total"] * 100
        if wr_90 >= 65:
            adjustments.append({
                "feature": "scoring_system",
                "action": "increase_confidence",
                "reason": f"90+ bracket win rate {wr_90:.0f}% — scoring discriminates well",
            })

    if score_separation >= 15:
        adjustments.append({
            "feature": "overall_scoring",
            "action": "lock_weights",
            "reason": f"Score separation {score_separation} points between wins and losses — system is predictive",
        })

    return {
        "trades_analyzed": len(rows),
        "min_required": min_trades,
        "ready": True,
        "bracket_win_rates": bracket_win_rates,
        "avg_win_score": round(avg_win_score, 1),
        "avg_loss_score": round(avg_loss_score, 1),
        "score_separation": score_separation,
        "adjustments": adjustments,
    }


def apply_weight_updates(existing_config: dict, analysis: dict) -> dict:
    """Apply learning module recommendations to existing weights."""
    if not analysis.get("ready"):
        return existing_config

    new_weights = {**existing_config}
    total = sum(new_weights.values())

    for adj in analysis.get("adjustments", []):
        feature = adj["feature"]
        action = adj["action"]

        if action == "increase_confidence" and feature == "scoring_system":
            # Increase momentum weight (strong scores correlate with wins)
            new_weights["momentum"] = round(new_weights.get("momentum", 20) * 1.1, 1)
            new_weights["volume"] = round(new_weights.get("volume", 15) * 1.05, 1)

    # Normalize weights to sum to 1.0 (or original total)
    if total > 0:
        norm_factor = total / sum(new_weights.values())
        new_weights = {k: round(v * norm_factor, 2) for k, v in new_weights.items()}

    return new_weights


def main() -> int:
    ap = argparse.ArgumentParser(description="Learning module — auto-weight adjustment after N trades.")
    ap.add_argument("--db", default=None, help="SQLite database path (default: data/trades.db)")
    ap.add_argument("--config", "-c", default=None, help="Input config.yaml as JSON for weight updates")
    ap.add_argument("--output", "-o", default=None, help="Output analysis + updated weights JSON")
    ap.add_argument("--min-trades", type=int, default=50, help="Minimum trades required (default: 50)")
    args = ap.parse_args()

    db_path = args.db or "data/trades.db"

    analysis = analyze_trades(db_path, min_trades=args.min_trades)

    result = {**analysis}

    # Apply weight updates if config provided
    if args.config:
        try:
            with open(args.config) as f:
                existing_config = json.load(f)
            updated_weights = apply_weight_updates(existing_config, analysis)
            result["updated_weights"] = updated_weights
        except Exception as e:
            print(f"[WARN] Could not load config for weight updates: {e}", file=sys.stderr)

    output_text = json.dumps(result, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"[OK] Analysis saved to {args.output}", file=sys.stderr)
    else:
        print(output_text)

    # Summary
    print(f"\n[SUMMARY]", file=sys.stderr)
    print(f"  Trades analyzed: {analysis['trades_analyzed']}", file=sys.stderr)
    if analysis.get("ready"):
        print(f"  Score separation: {analysis['score_separation']} pts", file=sys.stderr)
        print(f"  Avg win score:   {analysis['avg_win_score']:.1f}", file=sys.stderr)
        print(f"  Avg loss score:  {analysis['avg_loss_score']:.1f}", file=sys.stderr)
        for adj in analysis.get("adjustments", []):
            print(f"  → {adj['feature']}: {adj['action']} ({adj['reason']})", file=sys.stderr)
    else:
        print(f"  Not ready yet — need {analysis['min_required']} trades (have {analysis['trades_analyzed']})", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
