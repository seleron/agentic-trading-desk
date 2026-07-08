#!/usr/bin/env python3
"""
scoring_engine.py
=================
8-component scoring engine for BIST AI Trader v1.0 (pivot_risk +5 additive).

Scoring formula:
  Score = Trend(22) + Momentum(18) + Volume(15) + EMA Structure(15) + Pivot Position(10) + Volatility(10) + Technical Summary(5) + pivot_risk(+5, max 5)
  Total raw max: 105 → clamped to [0, 100] by final_score = min(100, raw_total)

Penalty system:
  RSI > 80         -> -10
  RSI < 35         -> -10
  MACD bearish     -> -15
  Volume low       -> -10
  EMA20 < EMA50    -> -20

Usage:
    python3 scripts/scoring_engine.py --input quotes.json --output scores.json
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from typing import Optional


# -- Scoring constants (configurable) ----------------------------------------

COMPONENT_WEIGHTS = {
    "trend": 17,
    "momentum": 18,
    "volume": 15,
    "ema_structure": 15,
    "pivot_position": 10,
    "volatility": 10,
    "pivot_risk": 5,
    "technical_summary": 5,
    "ichimoku_alignment": 5,
}

PENALTIES = {
    "rsi_overbought_max": 80,   # RSI > this -> -10
    "rsi_oversold_max": 35,     # RSI < this -> -10
    "volume_low_mult": 0.6,     # volume below 0.6× 20-day avg -> -10
    "ema_penalize_gap": True,   # EMA20 < EMA50 -> -20 (always)
}

# Momentum RSI zones (from spec)
RSI_HEALTHY = (50, 65)    # healthy trend
RSI_STRONG = (65, 75)     # strong momentum

# Relative Strength defaults (configurable via scoring.rs_threshold in config.yaml)
RS_DEFAULT_THRESHOLD = 0.05  # 5% relative outperformance for +1 modifier


def compute_trend_score(
    close: float,
    ema20: Optional[float],
    ema50: Optional[float],
    ema200: Optional[float] = None,
) -> tuple[int, list[str]]:
    """Trend scoring - max 25 points.

    EMA20 > EMA50 -> +15 (bullish alignment)
    EMA50 > EMA200 -> +10 (long trend confirmation) - ema200 optional
    Close above both EMAs -> +bonus up to +10
    """
    score = 0
    rationale: list[str] = []

    if ema20 is not None and ema50 is not None:
        if ema20 > ema50:
            score += 15
            rationale.append("EMA20 > EMA50 bullish alignment")
        else:
            score += 5  # partial credit for bearish

    # Long-term trend confirmation: EMA50 > EMA200 -> +10
    if ema50 is not None and ema200 is not None:
        if ema20 is not None and ema20 >= ema50 > ema200:
            score += 10
            rationale.append("EMA50 > EMA200 long trend confirmation")
        elif ema50 > ema200:
            score += 10
            rationale.append("EMA50 > EMA200 long-term bullish")

    # Close above both EMAs -> bonus (up to +10, but capped by total)
    if close > 0 and ema20 is not None and ema50 is not None:
        if close > ema20 and close > ema50:
            score += 10
            rationale.append(f"Close ({close:.2f}) above both EMAs")

    return min(score, 19), rationale


def compute_momentum_score(
    rsi: Optional[float], macd: float, macd_signal: float, close: float, ema20: Optional[float]
) -> tuple[int, list[str]]:
    """Momentum scoring - max 20 points.

    RSI zone-based:
      50-65 -> healthy trend (+10)
      65-75 -> strong momentum (+15)
      >80   -> overbought penalty applied later
    MACD bullish cross (macd > signal) -> +10
    Close above EMA20 -> +bonus
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

    return min(score, 16), rationale


def compute_volume_score(volume: float, volume_avg_20: float) -> tuple[int, list[str]]:
    """Volume scoring - max 15 points.

    Volume > 20-day avg -> +10 (volume spike confirmation)
    Volume > 1.5× avg -> +5 bonus (strong conviction)
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
    """EMA structure scoring - max 15 points.

    Clean bullish alignment (20 > 50 > 200) -> +10
    Partial alignments get proportional credit.
    Close near EMA20 (< 2% deviation) -> +bonus for pullback entry opportunity.
    """
    score = 0
    rationale: list[str] = []

    if ema20 is not None and ema50 is not None and ema200 is not None:
        if ema20 > ema50 > ema200:
            score += 10
            rationale.append("Clean bullish EMA stack (20>50>200)")

    if ema20 is not None and close > 0:
        dev = abs(close - ema20) / close * 100
        if dev < 2.0:
            score += 5
            rationale.append(f"Near EMA20 ({dev:.1f}% deviation) - pullback entry")

    return min(score, 15), rationale


def compute_pivot_score(
    close: float, pivot: Optional[float], r1: Optional[float], s1: Optional[float]
) -> tuple[int, list[str]]:
    """Pivot position scoring - max 10 points.

    Close between S1 and R1 -> neutral (+3)
    Close near support (S1 +/- 2%) -> +5 bounce opportunity
    Close above pivot but below R1 -> bullish continuation (+7)
    """
    score = 0
    rationale: list[str] = []

    if pivot is not None and close > 0:
        dist_from_pivot = (close - pivot) / pivot * 100

        if s1 is not None and r1 is not None:
            if s1 <= close <= r1:
                score += 3
                rationale.append(f"Between S1({s1}) and R1({r1}) - neutral zone")
            elif close < pivot:
                dist_from_s1 = abs(close - s1) / s1 * 100 if s1 > 0 else 999
                if dist_from_s1 < 2.0:
                    score += 7
                    rationale.append(f"Near support S1({s1:.2f}) - bounce opportunity")

    return min(score, 10), rationale


def compute_pivot_risk_score(
    close: float, pivot: Optional[float], r1: Optional[float], s1: Optional[float],
    r2: Optional[float] = None
) -> tuple[int, list[str]]:
    """Pivot risk scoring - max 5 points.

    Close safely between S1 and R1 (not near edges) -> +3
    Close above pivot with room to R2 -> +2 continuation signal
    """
    score = 0
    rationale: list[str] = []

    if close > 0 and pivot is not None and s1 is not None and r1 is not None:
        margin = 0.03 * close  # 3% margin from S1/R1 edges

        # Safely between S1 and R1 (not near edges)
        if close > s1 + margin and close < r1 - margin:
            score += 3
            rationale.append("Safely between S1 and R1 - low pivot risk")

        # Above pivot with room to R2 (bullish continuation)
        if close > pivot and r2 is not None and close < r2 - margin:
            score += 2
            rationale.append(f"Above pivot, below R2({r2:.2f}) - bullish continuation zone")

    return min(score, 5), rationale


def compute_volatility_score(high: float, low: float, close: float) -> tuple[int, list[str]]:
    """Volatility scoring - max 10 points.

    ATR-like measure: (high - low) / close ratio.
    Moderate volatility (2-5%) -> optimal for trading (+7)
    Very high (>8% intraday) -> risky (-penalty later, +3 base)
    Very low (<1%) -> no opportunity (+0)
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
            rationale.append(f"Elevated volatility ({atr_like:.1f}%) - watch risk")

    return min(score, 10), rationale


def compute_technical_summary_score(
    close: float, open_price: float, high: float, low: float
) -> tuple[int, list[str]]:
    """Technical summary scoring - max 5 points.

    Candlestick pattern recognition:
      Bullish engulfing / hammer -> +3
      Close in upper quarter of range -> +2
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
            rationale.append("Hammer candlestick - bullish reversal signal")

        # Close in upper quarter of daily range
        if close >= low + (high - low) * 0.75:
            score += 2
            rationale.append("Close in upper 25% of range - strong close")

    return min(score, 5), rationale


def compute_ichimoku_alignment_score(
    close: float, ichimoku: dict[str, Optional[float]] | None
) -> tuple[int, list[str]]:
    """Ichimoku alignment scoring - max 5 points.

    Price above cloud (Senkou A + Senkou B) with Tenkan > Kijun → bullish (+5)
    Price above cloud but Tenkan < Kijun → neutral/bearish cross (+3)
    No Ichimoku data or insufficient bars -> 0

    Args:
        close: Current close price.
        ichimoku: Dict from calculate_ichimoku() with tenkan_sen, kijun_sen,
                  senkou_span_a, senkou_span_b, chikou_span keys.

    Returns:
        (score, rationale) tuple.
    """
    score = 0
    rationale: list[str] = []

    if ichimoku is None or close <= 0:
        return 0, ["Ichimoku data unavailable — insufficient bars"]

    tenkan = ichimoku.get("tenkan_sen")
    kijun = ichimoku.get("kijun_sen")
    senkou_a = ichimoku.get("senkou_span_a")
    senkou_b = ichimoku.get("senkou_span_b")

    if tenkan is None or kijun is None or senkou_a is None or senkou_b is None:
        return 0, ["Ichimoku components incomplete"]

    cloud_top = max(senkou_a, senkou_b)
    cloud_bottom = min(senkou_a, senkou_b)

    # Price above cloud — bullish condition
    if close > cloud_top:
        # Tenkan > Kijun (bullish TK cross confirmed) -> +7
        if tenkan > kijun:
            score += 7
            rationale.append(
                f"Price ({close:.2f}) above cloud, Tenkan({tenkan:.2f}) > Kijun({kijun:.2f}) — strong bullish alignment"
            )
        else:
            # Price above cloud but TK cross bearish -> +3 (still bullish position)
            score += 3
            rationale.append(
                f"Price ({close:.2f}) above cloud but Tenkan ≤ Kijun — watch for TK cross"
            )

    return min(score, 5), rationale


def apply_penalties(rsi: Optional[float], volume: float, volume_avg_20: float, ema20: Optional[float], ema50: Optional[float]) -> tuple[int, list[str]]:
    """Apply penalty system from spec.

    RSI > 80 -> -10
    RSI < 35 -> -10
    Volume low (<60% of avg) -> -10
    EMA20 < EMA50 -> -20
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
            reasons.append("EMA20 < EMA50 - bearish structure")

    return -total_penalty, reasons


def compute_relative_strength(
    stock_closes: list[float],
    benchmark_closes: list[float],
    threshold: float = RS_DEFAULT_THRESHOLD,
    lookback: int = 20,
) -> dict:
    """Compute relative strength ratio of a stock vs. a benchmark index.

    The RS ratio is computed as the stock's return over benchmark's return
    for a configurable lookback window (default 20 days).

    RS ratio > (1 + threshold) → stock outperformed → modifier = +1
    RS ratio < (1 - threshold) → stock underperformed → modifier = -1
    Otherwise → neutral → modifier = 0

    Args:
        stock_closes: Close prices for the stock (latest at end).
        benchmark_closes: Close prices for the benchmark index (latest at end).
        threshold: Minimum relative outperformance/underperformance ratio.
                   Default 0.05 (= 5%).
        lookback: Number of recent bars to use for return computation.

    Returns:
        Dict with keys: ratio, direction (+1/-1/0), adjusted (bool),
        stock_return_pct, benchmark_return_pct.
    """
    n = min(len(stock_closes), len(benchmark_closes))
    if n < lookback + 1 or lookback < 1:
        return {
            "ratio": None,
            "direction": 0,
            "adjusted": False,
            "stock_return_pct": None,
            "benchmark_return_pct": None,
        }

    # Take the most recent `lookback+1` closes (index 0 = oldest in window)
    stock_window = stock_closes[-(lookback + 1):]
    bench_window = benchmark_closes[-(lookback + 1):]

    start_stock = float(stock_window[0])
    end_stock = float(stock_window[-1])
    start_bench = float(bench_window[0])
    end_bench = float(bench_window[-1])

    if start_stock <= 0 or start_bench <= 0:
        return {
            "ratio": None,
            "direction": 0,
            "adjusted": False,
            "stock_return_pct": None,
            "benchmark_return_pct": None,
        }

    stock_return = (end_stock - start_stock) / start_stock
    bench_return = (end_bench - start_bench) / start_bench

    # Avoid division by zero on benchmark return
    if abs(bench_return) < 1e-9:
        # Benchmark essentially flat — use absolute stock return vs threshold
        rs_ratio = end_stock / start_stock  # 1 + stock_return
    else:
        rs_ratio = (end_stock / start_stock) / (end_bench / start_bench)

    direction = 0
    adjusted = False
    if rs_ratio >= (1.0 + threshold):
        direction = 1
        adjusted = True
    elif rs_ratio <= (1.0 - threshold):
        direction = -1
        adjusted = True

    return {
        "ratio": round(rs_ratio, 6),
        "direction": direction,
        "adjusted": adjusted,
        "stock_return_pct": round(stock_return * 100, 2),
        "benchmark_return_pct": round(bench_return * 100, 2),
    }


def score_quote(quote: dict, correction=None, *,
                benchmark_closes: list[float] | None = None,
                rs_threshold: float = RS_DEFAULT_THRESHOLD) -> dict:
    """Score a single stock quote. Returns full scoring breakdown.

    Args:
        quote: Stock quote dict with OHLCV and indicator data.
        correction: Optional AdminCorrection for overrides.
        benchmark_closes: Optional list of benchmark close prices (latest at end).
                         Used to compute relative strength vs. a market index.
        rs_threshold: Relative strength threshold (fraction). Default 0.05 = 5%.
    """
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

    # Ichimoku data — passed from indicators compute() output
    ichimoku_data = quote.get("_ichimoku")

    # Volume average - require explicitly; skip volume component if absent.
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
        volume_reasons = ["volume_avg_20 missing - component skipped"]
    ema_struct_score, ema_reasons = compute_ema_structure_score(close, ema20, ema50, ema200)
    pivot_score_val, pivot_reasons = compute_pivot_score(close, pivot, r1, s1)
    r2 = quote.get("r2")
    pivot_risk_score_val, pivot_risk_reasons = compute_pivot_risk_score(
        close, pivot, r1, s1, r2
    )
    volatility_score_val, vol_reasons = compute_volatility_score(high, low, close)
    tech_summary_score, tech_reasons = compute_technical_summary_score(close, open_price, high, low)
    ichimoku_align_score, ichimoku_reasons = compute_ichimoku_alignment_score(close, ichimoku_data)

    raw_total = (trend_score + momentum_score + volume_score_val + ema_struct_score +
                 pivot_score_val + pivot_risk_score_val + volatility_score_val + tech_summary_score +
                 ichimoku_align_score)

    penalties, penalty_reasons = apply_penalties(
        rsi, volume, volume_avg_20 if volume_avg_20 is not None else 0.0, ema20, ema50
    )

    # Relative Strength modifier (post-hoc adjustment)
    original_score = max(0, min(100, raw_total + penalties))
    rs_info: dict = {
        "ratio": None,
        "direction": 0,
        "adjusted": False,
        "stock_return_pct": None,
        "benchmark_return_pct": None,
    }

    stock_closes = quote.get("stock_closes")
    if benchmark_closes is not None and stock_closes is not None:
        rs_info = compute_relative_strength(
            stock_closes, benchmark_closes, threshold=rs_threshold
        )
        # Apply +1/-1 modifier as post-hoc adjustment
        if rs_info["direction"] != 0:
            final_score = max(0, min(100, original_score + rs_info["direction"]))

    final_score = max(0, min(100, raw_total + penalties))

    all_reasons = (trend_reasons + momentum_reasons + volume_reasons + ema_reasons +
                   pivot_reasons + pivot_risk_reasons + vol_reasons + tech_reasons +
                   ichimoku_reasons + penalty_reasons)

    # Add RS rationale if applied
    if rs_info["adjusted"]:
        if rs_info["direction"] > 0:
            all_reasons.append(
                f"Relative strength outperformer (RS ratio={rs_info['ratio']:.4f}, "
                f"stock {rs_info['stock_return_pct']}% vs bench {rs_info['benchmark_return_pct']}%) -> +1 modifier"
            )
        else:
            all_reasons.append(
                f"Relative strength underperformer (RS ratio={rs_info['ratio']:.4f}, "
                f"stock {rs_info['stock_return_pct']}% vs bench {rs_info['benchmark_return_pct']}%) -> -1 modifier"
            )

    result = {
        "symbol": quote.get("symbol", "UNKNOWN"),
        "date": quote.get("date", ""),
        "score": final_score,
        "raw_components": {
            "trend": trend_score,
            "momentum": momentum_score,
            "volume": volume_score_val,
            "ema_structure": ema_struct_score,
            "pivot_position": pivot_score_val,
            "pivot_risk": pivot_risk_score_val,
            "volatility": volatility_score_val,
            "technical_summary": tech_summary_score,
            "ichimoku_alignment": ichimoku_align_score,
        },
        "penalties_applied": penalties,
        "rationale": all_reasons,
        "relative_strength": rs_info,
    }

    # Apply admin correction if present (must import locally to avoid circular deps)
    result["admin_override"] = None
    if correction is not None:
        _apply_correction(result, correction)

    return result


def _apply_correction(score: dict, correction) -> None:
    """Apply a single AdminCorrection to a scored quote dict (in-place)."""
    symbol = score.get("symbol", "")
    original_score = score["score"]

    otype = getattr(correction, "override_type", None) or ""
    rationale = getattr(correction, "rationale", "") or ""

    if otype == "force_buy":
        score["score"] = max(score["score"], 95)
        score["admin_override"] = {
            "type": "force_buy", "rationale": rationale,
            "original_score": original_score,
        }

    elif otype == "force_sell":
        score["score"] = min(score["score"], 15)
        score["admin_override"] = {
            "type": "force_sell", "rationale": rationale,
            "original_score": original_score,
        }

    elif otype == "ignore":
        score["score"] = -1  # below any threshold
        score["admin_override"] = {
            "type": "ignore", "rationale": rationale,
            "original_score": original_score,
        }

    elif otype == "custom_weight_modifier":
        raw_weights = dict(score.get("raw_components", {}))
        custom_w = getattr(correction, "weights", {}) or {}
        total_raw = sum(raw_weights.values()) if raw_weights else 1
        adjusted_total = 0.0

        for comp, val in raw_weights.items():
            new_weight = custom_w.get(comp)
            if new_weight is not None:
                adjusted_total += val * (new_weight / COMPONENT_WEIGHTS.get(comp, 1))
            else:
                adjusted_total += val

        # Clamp the adjusted score to [0, 100] range
        new_score = max(0, min(100, adjusted_total + score["penalties_applied"]))
        score["score"] = int(round(new_score))
        score["admin_override"] = {
            "type": "custom_weight_modifier", "rationale": rationale,
            "original_score": original_score, "adjusted_score": new_score,
        }


def score_quotes(
    quotes: list[dict],
    admin_corrections=None,
    *,
    benchmark_closes: list[float] | None = None,
    rs_threshold: float = RS_DEFAULT_THRESHOLD,
) -> list[dict]:
    """Score a batch of stock quotes.

    Args:
        quotes: List of quote dicts to score.
        admin_corrections: Optional dict mapping symbol → AdminCorrection for applying overrides.
        benchmark_closes: Optional list of benchmark close prices (latest at end).
                         Passed through to each score_quote call for RS computation.
        rs_threshold: Relative strength threshold (fraction). Default 0.05 = 5%.

    Returns:
        List of scored quote dicts with 'admin_override' and 'relative_strength' fields.
    """
    corrections = admin_corrections or {}
    return [
        score_quote(q, corrections.get(q.get("symbol", "")),
                    benchmark_closes=benchmark_closes, rs_threshold=rs_threshold)
        for q in quotes
    ]


def select_top_picks(scores: list[dict], threshold: int = 80, top_n: int = 2) -> dict:
    """Selection engine - picks stocks above threshold.

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
