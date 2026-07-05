#!/usr/bin/env python3
"""
scoring_engine.py
=================
7-component scoring engine for BIST AI Trader v1.0.

Scoring formula (from spec):
  Score = Trend(25) + Momentum(20) + Volume(15) + EMA Structure(15) + Pivot Position(10) + Volatility(10) + Technical Summary(5)

Penalty system:
  RSI > 80         → -10
  RSI < 35         → -10
  MACD bearish     → -15
  Volume low       → -10
  EMA20 < EMA50    → -20

Usage:
    python3 scripts/scoring_engine.py --input quotes.json --output scores.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Optional


# ── Scoring constants (configurable) ────────────────────────────────────────

COMPONENT_WEIGHTS = {
    "trend": 25,
    "momentum": 20,
    "volume": 15,
    "ema_structure": 15,
    "pivot_position": 10,
    "volatility": 10,
    "technical_summary": 5,
}

PENALTIES = {
    "rsi_overbought_max": 80,   # RSI > this → -10
    "rsi_oversold_max": 35,     # RSI < this → -10
    "volume_low_mult": 0.6,     # volume below 0.6× 20-day avg → -10
    "ema_penalize_gap": True,   # EMA20 < EMA50 → -20 (always)
}

# Momentum RSI zones (from spec)
RSI_HEALTHY = (50, 65)    # healthy trend
RSI_STRONG = (65, 75)     # strong momentum


def compute_trend_score(
    close: float,
    ema20: Optional[float],
    ema50: Optional[float],
    ema200: Optional[float] = None,
) -> tuple[int, list[str]]:
    """Trend scoring — max 25 points.

    EMA20 > EMA50 → +15 (bullish alignment)
    EMA50 > EMA200 → +10 (long trend confirmation) — ema200 optional
    Close above both EMAs → +bonus up to +10
    """
    score = 0
    rationale: list[str] = []

    if ema20 is not None and ema50 is not None:
        if ema20 > ema50:
            score += 15
            rationale.append("EMA20 > EMA50 bullish alignment")
        else:
            score += 5  # partial credit for bearish

    # Long-term trend confirmation: EMA50 > EMA200 → +10
    if ema50 is not None and ema200 is not None:
        if ema20 is not None and ema20 >= ema50 > ema200:
            score += 10
            rationale.append("EMA50 > EMA200 long trend confirmation")
        elif ema50 > ema200:
            score += 10
            rationale.append("EMA50 > EMA200 long-term bullish")

    # Close above both EMAs → bonus (up to +10, but capped by total)
    if close > 0 and ema20 is not None and ema50 is not None:
        if close > ema20 > ema50:
            score += 10
            rationale.append(f"Close ({close:.2f}) above both EMAs")

    return min(score, 25), rationale


def compute_momentum_score(
    rsi: Optional[float], macd: float, macd_signal: float, close: float, ema20: Optional[float]
) -> tuple[int, list[str]]:
    """Momentum scoring — max 20 points.

    RSI zone-based:
      50–65 → healthy trend (+10)
      65–75 → strong momentum (+15)
      >80   → overbought penalty applied later
    MACD bullish cross (macd > signal) → +10
    Close above EMA20 → +bonus
    """
    score = 0
    rationale: list[str] = []

    if rsi is not None:
        lo, hi = RSI_HEALTHY
        if lo <= rsi <= hi:
            score += 10
            rationale.append(f"RSI {rsi:.0f} healthy trend zone")
        elif RSI_STRONG[0] < rsi <= RSI_STRONG[1]:
            score += 15
            rationale.append(f"RSI {rsi:.0f} strong momentum zone")

    if macd > macd_signal:
        score += 10
        rationale.append("MACD bullish (above signal)")

    return min(score, 20), rationale


def compute_volume_score(volume: float, volume_avg_20: float) -> tuple[int, list[str]]:
    """Volume scoring — max 15 points.

    Volume > 20-day avg → +10 (volume spike confirmation)
    Volume > 1.5× avg → +5 bonus (strong conviction)
    """
    score = 0
    rationale: list[str] = []

    if volume_avg_20 > 0 and volume >= volume_avg_20:
        score += 10
        rationale.append(f"Volume {volume/1e6:.1f}M ≥ 20-day avg")
        if volume >= 1.5 * volume_avg_20:
            score += 5
            rationale.append("Strong conviction (vol > 1.5× avg)")

    return min(score, 15), rationale


def compute_ema_structure_score(
    close: float, ema20: Optional[float], ema50: Optional[float], ema200: Optional[float]
) -> tuple[int, list[str]]:
    """EMA structure scoring — max 15 points.

    Clean bullish alignment (200 > 50 > 20 > close) → +15
    Partial alignments get proportional credit.
    Close near EMA20 (< 2% deviation) → +bonus for pullback entry opportunity.
    """
    score = 0
    rationale: list[str] = []

    if ema20 is not None and ema50 is not None and ema200 is not None:
        if ema200 > ema50 > ema20:
            score += 10
            rationale.append("Clean bullish EMA stack (200>50>20)")

    if ema20 is not None and close > 0:
        dev = abs(close - ema20) / close * 100
        if dev < 2.0:
            score += 5
            rationale.append(f"Near EMA20 ({dev:.1f}% deviation) — pullback entry")

    return min(score, 15), rationale


def compute_pivot_score(
    close: float, pivot: Optional[float], r1: Optional[float], s1: Optional[float]
) -> tuple[int, list[str]]:
    """Pivot position scoring — max 10 points.

    Close between S1 and R1 → neutral (+3)
    Close near support (S1 ± 2%) → +5 bounce opportunity
    Close above pivot but below R1 → bullish continuation (+7)
    """
    score = 0
    rationale: list[str] = []

    if pivot is not None and close > 0:
        dist_from_pivot = (close - pivot) / pivot * 100

        if s1 is not None and r1 is not None:
            if s1 <= close <= r1:
                score += 3
                rationale.append(f"Between S1({s1}) and R1({r1}) — neutral zone")
            elif close < pivot:
                dist_from_s1 = abs(close - s1) / s1 * 100 if s1 > 0 else 999
                if dist_from_s1 < 2.0:
                    score += 7
                    rationale.append(f"Near support S1({s1:.2f}) — bounce opportunity")

    return min(score, 10), rationale


def compute_volatility_score(high: float, low: float, close: float) -> tuple[int, list[str]]:
    """Volatility scoring — max 10 points.

    ATR-like measure: (high - low) / close ratio.
    Moderate volatility (2–5%) → optimal for trading (+7)
    Very high (>8% intraday) → risky (-penalty later, +3 base)
    Very low (<1%) → no opportunity (+0)
    """
    score = 0
    rationale: list[str] = []

    if close > 0 and high > low:
        atr_like = (high - low) / close * 100

        if 2.0 <= atr_like <= 5.0:
            score += 7
            rationale.append(f"Optimal intraday volatility ({atr_like:.1f}%)")
        elif atr_like > 5.0 and atr_like <= 8.0:
            score += 5
            rationale.append(f"Elevated volatility ({atr_like:.1f}%) — watch risk")

    return min(score, 10), rationale


def compute_technical_summary_score(
    close: float, open_price: float, high: float, low: float
) -> tuple[int, list[str]]:
    """Technical summary scoring — max 5 points.

    Candlestick pattern recognition:
      Bullish engulfing / hammer → +3
      Close in upper quarter of range → +2
    """
    score = 0
    rationale: list[str] = []

    if high > low and close > 0:
        body = abs(close - open_price) / close * 100
        upper_shadow = (high - max(open_price, close)) / close * 100 if close > 0 else 0
        lower_shadow = (min(open_price, close) - low) / close * 100 if close > 0 else 0

        # Hammer: small body at top, long lower shadow (>2× body)
        if upper_shadow < 5 and lower_shadow > body and lower_shadow > 3:
            score += 3
            rationale.append("Hammer candlestick — bullish reversal signal")

        # Close in upper quarter of daily range
        if close >= low + (high - low) * 0.75:
            score += 2
            rationale.append("Close in upper 25% of range — strong close")

    return min(score, 5), rationale


def apply_penalties(rsi: Optional[float], volume: float, volume_avg_20: float, ema20: Optional[float], ema50: Optional[float]) -> tuple[int, list[str]]:
    """Apply penalty system from spec.

    RSI > 80 → -10
    RSI < 35 → -10
    Volume low (<60% of avg) → -10
    EMA20 < EMA50 → -20
    """
    total_penalty = 0
    reasons: list[str] = []

    if rsi is not None and rsi > PENALTIES["rsi_overbought_max"]:
        total_penalty += 10
        reasons.append(f"RSI {rsi:.0f} overbought (>{PENALTIES['rsi_overbought_max']})")

    if rsi is not None and rsi < PENALTIES["rsi_oversold_max"]:
        total_penalty += 10
        reasons.append(f"RSI {rsi:.0f} oversold (<{PENALTIES['rsi_oversold_max']})")

    if volume_avg_20 > 0 and volume < PENALTIES["volume_low_mult"] * volume_avg_20:
        total_penalty += 10
        reasons.append(f"Volume below {PENALTIES['volume_low_mult']}× avg ({volume/1e6:.1f}M vs {volume_avg_20/1e6:.1f}M)")

    if ema20 is not None and ema50 is not None and PENALTIES["ema_penalize_gap"]:
        if ema20 < ema50:
            total_penalty += 20
            reasons.append("EMA20 < EMA50 — bearish structure")

    return -total_penalty, reasons


def score_quote(quote: dict) -> dict:
    """Score a single stock quote. Returns full scoring breakdown."""
    close = quote["close"]
    high = quote.get("high", close)
    low = quote.get("low", close)
    open_price = quote.get("open", close)
    volume = quote.get("volume", 0)

    rsi = quote.get("rsi")
    macd = quote.get("macd", 0)
    macd_signal = quote.get("macd_signal", 0)
    ema20 = quote.get("ema20")
    ema50 = quote.get("ema50")
    ema200 = quote.get("ema200")
    pivot = quote.get("pivot")
    r1 = quote.get("r1")
    s1 = quote.get("s1")

    # Volume average — require explicitly; skip volume component if absent.
    raw_volume_avg_20 = quote.get("volume_avg_20")
    volume_avg_20: Optional[float] = None
    if raw_volume_avg_20 is not None and raw_volume_avg_20 > 0:
        volume_avg_20 = float(raw_volume_avg_20)

    # Compute each component
    trend_score, trend_reasons = compute_trend_score(close, ema20, ema50, ema200)
    momentum_score, momentum_reasons = compute_momentum_score(rsi, macd, macd_signal, close, ema20)
    if volume_avg_20 is not None:
        volume_score_val, volume_reasons = compute_volume_score(volume, volume_avg_20)
    else:
        volume_score_val = 0
        volume_reasons = ["volume_avg_20 missing — component skipped"]
    ema_struct_score, ema_reasons = compute_ema_structure_score(close, ema20, ema50, ema200)
    pivot_score_val, pivot_reasons = compute_pivot_score(close, pivot, r1, s1)
    volatility_score_val, vol_reasons = compute_volatility_score(high, low, close)
    tech_summary_score, tech_reasons = compute_technical_summary_score(close, open_price, high, low)

    raw_total = (trend_score + momentum_score + volume_score_val + ema_struct_score +
                 pivot_score_val + volatility_score_val + tech_summary_score)

    penalties, penalty_reasons = apply_penalties(
        rsi, volume, volume_avg_20 if volume_avg_20 is not None else 0.0, ema20, ema50
    )
    final_score = max(0, min(100, raw_total + penalties))

    all_reasons = (trend_reasons + momentum_reasons + volume_reasons + ema_reasons +
                   pivot_reasons + vol_reasons + tech_reasons + penalty_reasons)

    return {
        "symbol": quote.get("symbol", "UNKNOWN"),
        "date": quote.get("date", ""),
        "score": final_score,
        "raw_components": {
            "trend": trend_score,
            "momentum": momentum_score,
            "volume": volume_score_val,
            "ema_structure": ema_struct_score,
            "pivot_position": pivot_score_val,
            "volatility": volatility_score_val,
            "technical_summary": tech_summary_score,
        },
        "penalties_applied": penalties,
        "rationale": all_reasons,
    }


def score_quotes(quotes: list[dict]) -> list[dict]:
    """Score a batch of stock quotes."""
    return [score_quote(q) for q in quotes]


def select_top_picks(scores: list[dict], threshold: int = 80, top_n: int = 2) -> dict:
    """Selection engine — picks stocks above threshold.

    Returns structured output per spec:
      - top_picks: up to N stocks with score > threshold
      - market_bias: derived from average score of all scored quotes
      - no_trade_day flag if fewer than N qualify
    """
    qualified = sorted(scores, key=lambda s: s["score"], reverse=True)
    above_threshold = [s for s in qualified if s["score"] >= threshold]

    top_picks = above_threshold[:top_n]
    market_bias = "neutral"
    avg_score = sum(s["score"] for s in scores) / len(scores) if scores else 0

    if avg_score > 55:
        market_bias = "positive"
    elif avg_score < 45:
        market_bias = "negative"

    result = {
        "no_trade_day": len(top_picks) < top_n,
        "market_bias": market_bias,
        "avg_score_all_stocks": round(avg_score, 1),
        "total_scanned": len(scores),
        "qualified_above_threshold": len(above_threshold),
        "top_picks": [],
    }

    for pick in top_picks:
        result["top_picks"].append({
            "symbol": pick["symbol"],
            "score": pick["score"],
            "rationale": pick["rationale"],
            "raw_components": pick["raw_components"],
        })

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="7-component scoring engine for BIST AI Trader v1.0.")
    ap.add_argument("--input", "-i", required=True, help="Input JSON file with stock quotes")
    ap.add_argument("--output", "-o", default=None, help="Output JSON file for scores")
    ap.add_argument("--threshold", type=int, default=80, help="Score threshold for picks (default: 80)")
    ap.add_argument("--top-n", type=int, default=2, help="Number of top picks (default: 2)")
    args = ap.parse_args()

    try:
        with open(args.input) as f:
            quotes = json.load(f)
        if isinstance(quotes, dict):
            quotes = quotes.get("quotes", [quotes])
    except Exception as e:
        print(f"[ERROR] Failed to load input: {e}", file=sys.stderr)
        return 1

    scores = score_quotes(quotes)
    selection = select_top_picks(scores, threshold=args.threshold, top_n=args.top_n)

    output = {"scores": scores, "selection": selection}
    output_text = json.dumps(output, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"[OK] Scores saved to {args.output}", file=sys.stderr)
    else:
        print(output_text)

    # Summary to stderr
    print(f"\n[SUMMARY]", file=sys.stderr)
    print(f"  Stocks scored:     {selection['total_scanned']}", file=sys.stderr)
    print(f"  Qualified (>={args.threshold}): {selection['qualified_above_threshold']}", file=sys.stderr)
    print(f"  Market bias:       {selection['market_bias']}", file=sys.stderr)
    for pick in selection["top_picks"]:
        print(f"  PICK: {pick['symbol']} score={pick['score']}", file=sys.stderr)
    if selection["no_trade_day"]:
        print("  ** NO TRADE DAY **", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
