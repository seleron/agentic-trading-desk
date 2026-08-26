#!/usr/bin/env python3
"""Ad-hoc BIST watchlist scan via the desk's real scoring_engine + indicators.

Data: borsapy (BIST). Benchmark for relative strength: THYAO.IS.
Usage: python3 watchlist_scan.py
"""
import os
import sys
import json
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

from borsapy import Tickers
from scoring_engine import score_quote
from indicators import compute

TICKERS = [
    "EREGL", "ANHYT", "TUPRS", "TKFEN", "THYAO", "ASELS",  # user's explicit list
    "AKBNK", "GARAN", "ISCTR", "KOZAA", "KRDMD", "ECILC", "ARCLK", "BIMAS", "ASML",  # broad basket
]
BENCHMARK = "THYAO"
RS_THRESHOLD = 0.05  # matches config.yaml scoring.rs_threshold


def fetch(ticker: str):
    tk = Tickers(ticker)
    df = tk.history(period="2y", interval="1d")
    if df is None or len(df) < 50:
        return None
    rows = df.reset_index()
    dates = [str(d.date() if hasattr(d, "date") else d) for d in rows["Date"]]
    closes = [float(x) for x in rows["Close"].tolist()]
    highs = [float(x) for x in rows["High"].tolist()]
    lows = [float(x) for x in rows["Low"].tolist()]
    opens = [float(x) for x in rows["Open"].tolist()]
    vols = [float(x) for x in rows["Volume"].tolist()]
    return dict(dates=dates, closes=closes, highs=highs, lows=lows, opens=opens, vols=vols)


def build_quote(ticker: str, d: dict) -> dict:
    closes, highs, lows, vols = d["closes"], d["highs"], d["lows"], d["vols"]
    opens = d["opens"]
    ind = compute(closes, highs=highs, lows=lows, volumes=vols)

    # Pivot points from the most recent 3 complete bars (R2 = highest high, S2 = lowest low).
    p_close = closes[-2]
    p_high, p_low = highs[-2], lows[-2]
    p_prev_high = max(highs[-3], highs[-2])
    p_prev_low = min(lows[-3], lows[-2])
    pivot = (p_high + p_low + p_close) / 3.0
    r1 = 2 * pivot - p_low
    s1 = 2 * pivot - p_high
    r2 = max(highs[-3], highs[-2])
    s2 = min(lows[-3], lows[-2])

    volume_avg_20 = sum(vols[-21:-1]) / 20.0

    q = {
        "symbol": f"{ticker}.IS",
        "date": d["dates"][-1],
        "open": opens[-1],
        "high": highs[-1],
        "low": lows[-1],
        "close": closes[-1],
        "volume": vols[-1],
        "volume_avg_20": volume_avg_20,
        "vol_ratio": (vols[-1] / volume_avg_20) if volume_avg_20 else None,
        "ema5": ind.get("ema5") or None,
        "ema9": ind.get("ema9") or None,
        "ema20": ind.get("ema20"),
        "ema50": ind.get("ema50"),
        "ema200": ind.get("ema200"),
        "rsi": ind.get("rsi14"),
        "macd": ind.get("macd_line"),
        "macd_signal": ind.get("macd_signal"),
        "bb_upper": ind.get("bb_upper"),
        "bb_mid": ind.get("bb_mid"),
        "bb_lower": ind.get("bb_lower"),
        "bb_width": (ind.get("bb_upper") - ind.get("bb_lower")) if ind.get("bb_upper") and ind.get("bb_lower") else None,
        "pivot": pivot,
        "r1": r1,
        "s1": s1,
        "r2": r2,
        "_ichimoku": ind.get("ichimoku"),
        "close_series": closes,
    }
    return q


def main():
    # Benchmark closes
    bench_data = fetch(BENCHMARK)
    if bench_data is None:
        print("FATAL: could not fetch benchmark THYAO")
        return
    bench_closes = bench_data["closes"]

    results = []
    errors = []
    for t in TICKERS:
        try:
            d = fetch(t)
            if d is None:
                errors.append(f"{t}: no/insufficient data")
                continue
            q = build_quote(t, d)
            sc = score_quote(q, benchmark_closes=bench_closes, rs_threshold=RS_THRESHOLD)
            d1 = sc["relative_strength"] if "relative_strength" in sc else {}
            results.append({
                "symbol": t,
                "date": q["date"],
                "close": round(q["close"], 2),
                "score": sc["score"],
                "rs_dir": d1.get("direction", 0),
                "stock_ret_20d": round(d1.get("stock_return_pct", 0) * 100, 2),
                "bench_ret_20d": round(d1.get("benchmark_return_pct", 0) * 100, 2),
                "rsi": round(sc.get("raw_components", {}).get("momentum") is not None and (q["rsi"] or 0), 1),
                "rsi_val": round(q["rsi"], 1) if q["rsi"] is not None else None,
                "ema200_up": (q["close"] > q["ema200"]) if q["ema200"] else None,
                "penalties": sc["penalties_applied"],
                "turnover_20m_try": round(q["volume_avg_20"] * (q["close"] if q["close"] else 0), 0),
                "comps": {k: v for k, v in sc["raw_components"].items()},
                "rationale": sc["rationale"],
            })
        except Exception as e:
            errors.append(f"{t}: {type(e).__name__}: {e}")

    results.sort(key=lambda r: r["score"], reverse=True)
    bench_20d = (bench_closes[-1] / bench_closes[-21] - 1) * 100
    print("=== BIST WATCHLIST SCAN — scoring_engine v1.0 (9-component) ===")
    print(f"Benchmark: {BENCHMARK}.IS  20d return: {bench_20d:.2f}%")
    print(f"RS threshold: +/-{RS_THRESHOLD*100:.0f}% over 20d\n")
    print(f"{'RANK':<4}{'SYM':<7}{'SCORE':<6}{'RSI':<6}{'20d%':<8}{'RS':<4}{'200EMA':<8}{'PEN':<5}{'CLOSE':>9}")
    for i, r in enumerate(results, 1):
        up = "^" if r["ema200_up"] else "v" if r["ema200_up"] is False else "?"
        print(f"{i:<4}{r['symbol']:<7}{r['score']:<6}{str(r['rsi_val']):<6}{r['stock_ret_20d']:<8.2f}{r['rs_dir']:+d}{'':<1}{up:<8}{r['penalties']:<5}{r['close']:>9.2f}")
    print("\n--- TIERS ---")
    for r in results:
        tier = "STRONG BUY" if r["score"] >= 85 else "WATCHLIST" if r["score"] >= 70 else "NO-TRADE"
        if r["score"] >= 70:
            print(f"  [{tier}] {r['symbol']} {r['score']}")
    if errors:
        print("\n--- ERRORS ---")
        for e in errors:
            print("  " + e)
    print("\n--- RATIONALE (top 5) ---")
    for r in results[:5]:
        print(f"\n{r['symbol']} ({r['score']}):")
        for line in r["rationale"][:10]:
            print(f"   - {line}")


if __name__ == "__main__":
    main()
