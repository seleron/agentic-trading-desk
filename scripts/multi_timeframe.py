#!/usr/bin/env python3
"""
multi_timeframe.py
==================
Multi-timeframe confirmation engine.

Analyzes the same asset across multiple timeframes to determine
trend alignment and entry signal strength. Uses a hierarchical
scoring approach: higher timeframes dominate, lower timeframes
provide timing signals.

Usage:
    python3 scripts/multi_timeframe.py --input mtf_input.json [--json]
    cat mtf_input.json | python3 scripts/multi_timeframe.py --stdin

Stdlib only. Requires pre-fetched data for each timeframe.
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional


def compute_single_tf_score(
    closes: list[float],
) -> dict:
    """
    Compute a simplified trend score for a single close series.
    Uses EMA alignment (same logic as original indicators.py).
    """
    if len(closes) < 50:
        return {"score": 0, "reason": "insufficient_data", "n_bars": len(closes)}

    def ema(values: list[float], period: int) -> Optional[float]:
        if len(values) < period:
            return None
        k = 2.0 / (period + 1)
        seed = sum(values[:period]) / period
        prev = seed
        for i in range(period, len(values)):
            prev = values[i] * k + prev * (1 - k)
        return prev

    e20 = ema(closes, 20)
    e50 = ema(closes, 50)
    e200 = ema(closes, 200) if len(closes) >= 200 else None
    current = closes[-1]

    score = 0
    reasons = []

    if e20 and current > e20:
        score += 1
        reasons.append("price_above_ema20")
    elif e20:
        score -= 1
        reasons.append("price_below_ema20")

    if e20 and e50:
        if e20 > e50:
            score += 1
            reasons.append("ema20_above_ema50")
        else:
            score -= 1
            reasons.append("ema20_below_ema50")

    if e50 and e200:
        if e50 > e200:
            score += 1
            reasons.append("ema50_above_ema200")
        else:
            score -= 1
            reasons.append("ema50_below_ema200")

    return {
        "score": max(-3, min(3, score)),
        "reasons": reasons,
        "n_bars": len(closes),
        "ema20": round(e20, 4) if e20 else None,
        "ema50": round(e50, 4) if e50 else None,
        "ema200": round(e200, 4) if e200 else None,
    }


def multi_timeframe_analysis(
    symbol: str,
    timeframe_scores: dict[str, list[float]],
    weights: Optional[dict] = None,
) -> dict:
    """
    Perform multi-timeframe analysis and produce a consensus score.

    Args:
        symbol: Trading pair/ticker
        timeframe_scores: Dict mapping timeframe ("1d", "4h", "15m") -> close prices
        weights: Optional custom weights for timeframes (defaults to higher TF weight)

    Returns:
        Analysis result with consensus score and per-TF breakdown
    """
    if not weights:
        # Default: higher timeframes get more weight
        default_weights = {
            "1w": 0.40,
            "1d": 0.35,
            "4h": 0.15,
            "1h": 0.10,
            "15m": 0.00,
        }
    else:
        default_weights = weights

    # Score each timeframe
    tf_results = {}
    for tf, closes in timeframe_scores.items():
        result = compute_single_tf_score(closes)
        weight = default_weights.get(tf, 0.10)
        tf_results[tf] = {
            **result,
            "weight": weight,
        }

    # Weighted consensus score (-3 to +3 range)
    total_weight = sum(r["weight"] for r in tf_results.values())
    if total_weight == 0:
        return {"error": "No valid weights"}

    weighted_sum = sum(
        r["score"] * r["weight"] for r in tf_results.values()
    )
    consensus_score = round(weighted_sum / total_weight, 2)

    # Alignment check: are all significant TFs agreeing?
    aligned_tfs = [tf for tf, r in tf_results.items() if r.get("n_bars", 0) >= 50]
    scores_aligned = [r["score"] for r in tf_results.values() if r.get("n_bars", 0) >= 50]

    all_same_direction = len(set(1 if s > 0 else -1 for s in scores_aligned)) <= 1 if scores_aligned else False
    partial_alignment = any(s != consensus_score and abs(s) == abs(consensus_score) for s in scores_aligned) if scores_aligned else False

    # Generate recommendation
    if consensus_score >= 2.0:
        recommendation = "STRONG BUY"
    elif consensus_score >= 1.0:
        recommendation = "BUY"
    elif consensus_score <= -2.0:
        recommendation = "STRONG SELL"
    elif consensus_score <= -1.0:
        recommendation = "SELL"
    else:
        recommendation = "NEUTRAL / WAIT"

    return {
        "symbol": symbol,
        "consensus_score": consensus_score,
        "recommendation": recommendation,
        "all_timeframes_aligned": all_same_direction,
        "timeframes": tf_results,
        "notes": [
            f"Consensus based on {len(aligned_tfs)} aligned timeframe(s)",
            f"Alignment: {'STRONG' if all_same_direction else 'PARTIAL' if partial_alignment else 'MIXED'}",
        ],
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Multi-timeframe confirmation engine."
    )
    ap.add_argument("--input", "-i", help="JSON input file")
    ap.add_argument("--stdin", action="store_true", help="Read from stdin")
    ap.add_argument("--json", action="store_true", help="Output JSON format")
    args = ap.parse_args()

    # Load input
    if args.stdin:
        raw = sys.stdin.read()
        data = json.loads(raw)
    elif args.input:
        with open(args.input) as f:
            data = json.load(f)
    else:
        print("[ERROR] Provide --input or use --stdin", file=sys.stderr)
        return 1

    try:
        symbol = data.get("symbol", "UNKNOWN")
        timeframe_scores = data.get("timeframes", {})

        result = multi_timeframe_analysis(symbol, timeframe_scores)

        output = json.dumps(result, indent=2, ensure_ascii=False)

        if args.json or True:  # Always JSON for MTF results
            print(output)
        else:
            render_result(result)

        return 0
    except Exception as e:
        error_result = {"error": str(e)}
        print(json.dumps(error_result, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


def render_result(r: dict) -> None:
    """Human-readable rendering of multi-timeframe results."""
    if "error" in r:
        print(f"[ERROR] {r['error']}")
        return

    L = []
    L.append(f"MULTI-TIMEFRAME ANALYSIS  ·  {r['symbol']}")
    L.append("=" * 50)
    L.append(f"Consensus Score:   {r['consensus_score']:+.2f}")
    L.append(f"Recommendation:    {r['recommendation']}")
    L.append(f"All Aligned:       {'Yes' if r['all_timeframes_aligned'] else 'No'}")
    L.append("-" * 50)

    for tf, result in sorted(r["timeframes"].items(), reverse=True):
        arrow = "▲" if result.get("score", 0) > 0 else ("▼" if result.get("score", 0) < 0 else "─")
        w = result.get("weight", 0)
        L.append(f"  {arrow} {tf:<4} score={result.get('score', '?'):+d}  w={w:.2f}")

    if r["notes"]:
        L.append("-" * 50)
        for note in r["notes"]:
            L.append(f"  note: {note}")

    print("\n".join(L))


if __name__ == "__main__":
    raise SystemExit(main())
