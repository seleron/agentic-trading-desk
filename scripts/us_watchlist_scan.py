#!/usr/bin/env python3
"""Ad-hoc US stock watchlist scan via the desk's real scoring_engine + indicators.

Data: yfinance (no .IS suffix -> US ticker). Benchmark for relative strength: ^GSPC.
Usage: python3 us_watchlist_scan.py [TICKER ...]
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "scripts"))

import yfinance as yf
from scoring_engine import score_quote
from indicators import compute

TICKERS = sys.argv[1:] or ["OBDC", "ARCC", "MAIN"]
BENCHMARK = "^GSPC"
RS_THRESHOLD = 0.05


def fetch(ticker: str):
    df = yf.download(ticker, period="2y", interval="1d",
                     progress=False, auto_adjust=True)
    if df is None or len(df) < 50:
        return None
    if isinstance(df.columns, pd.MultiIndex if False else type(df.columns)):
        pass
    # Flatten multiindex columns if present
    if hasattr(df.columns, "droplevel"):
        try:
            df.columns = df.columns.droplevel(-1)
        except Exception:
            pass
    rows = df.reset_index()
    date_col = "Date" if "Date" in rows.columns else rows.columns[0]
    dates = [str(d) for d in rows[date_col].tolist()]
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

    # Pivot points from the most recent 3 complete bars (mirrors watchlist_scan.py)
    p_close = closes[-2]
    p_high, p_low = highs[-2], lows[-2]
    pivot = (p_high + p_low + p_close) / 3.0
    r1 = 2 * pivot - p_low
    s1 = 2 * pivot - p_high
    r2 = max(highs[-3], highs[-2])

    volume_avg_20 = sum(vols[-21:-1]) / 20.0

    q = {
        "symbol": ticker,
        "date": d["dates"][-1],
        "open": opens[-1],
        "high": highs[-1],
        "low": lows[-1],
        "close": closes[-1],
        "volume": vols[-1],
        "volume_avg_20": volume_avg_20,
        "vol_ratio": (vols[-1] / volume_avg_20) if volume_avg_20 else None,
        "ema5": None,
        "ema9": None,
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
    bench_data = fetch(BENCHMARK)
    if bench_data is None:
        print("FATAL: could not fetch benchmark S&P 500")
        sys.exit(1)
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
            ret5 = (q["close"] / q["close_series"][-6] - 1) * 100 if len(q["close_series"]) >= 6 else None
            ret20 = (q["close"] / q["close_series"][-21] - 1) * 100 if len(q["close_series"]) >= 21 else None
            results.append({
                "symbol": t,
                "date": q["date"],
                "close": round(q["close"], 2),
                "score": sc["score"],
                "rs_dir": d1.get("direction", 0),
                "stock_ret_5d": round(ret5, 2) if ret5 is not None else None,
                "stock_ret_20d": round(ret20, 2) if ret20 is not None else None,
                "bench_ret_20d": d1.get("benchmark_return_pct"),
                "rsi": round(q["rsi"], 1) if q["rsi"] is not None else None,
                "ema200_up": (q["close"] > q["ema200"]) if q["ema200"] else None,
                "above_ema200_pct": round((q["close"] / q["ema200"] - 1) * 100, 1) if q["ema200"] else None,
                "penalties": sc["penalties_applied"],
                "bb_width": round(q["bb_width"], 3) if q["bb_width"] else None,
                "comps": {k: v for k, v in sc["raw_components"].items()},
                "rationale": sc["rationale"],
            })
        except Exception as e:
            errors.append(f"{t}: {type(e).__name__}: {e}")

    results.sort(key=lambda r: r["score"], reverse=True)
    bench_20d = (bench_closes[-1] / bench_closes[-21] - 1) * 100
    print("=== US WATCHLIST SCAN — scoring_engine v1.0 (9-component) ===")
    print(f"Benchmark: {BENCHMARK}  20d return: {bench_20d:.2f}%")
    print(f"RS threshold: +/-{RS_THRESHOLD*100:.0f}%\n")
    print(f"{'RANK':<4}{'SYM':<7}{'SCORE':<6}{'RSI':<6}{'5d%':<8}{'20d%':<8}{'RS':<4}{'200EMA%':<9}{'PEN':<5}{'BB_W':<7}{'CLOSE':>9}")
    for i, r in enumerate(results, 1):
        print(f"{i:<4}{r['symbol']:<7}{r['score']:<6}{str(r['rsi']):<6}{str(r['stock_ret_5d']):<8}"
              f"{r['stock_ret_20d']:<8.2f}{r['rs_dir']:+d}{'':<1}{str(r['above_ema200_pct']):<9}"
              f"{r['penalties']:<5}{str(r['bb_width']):<7}{r['close']:>9.2f}")
    print("\n--- TIERS ---")
    for r in results:
        tier = "STRONG BUY" if r["score"] >= 85 else "WATCHLIST" if r["score"] >= 70 else "NO-TRADE"
        print(f"  [{tier}] {r['symbol']} {r['score']}")
    if errors:
        print("\n--- ERRORS ---")
        for e in errors:
            print("  " + e)
    print("\n--- RATIONALE ---")
    for r in results:
        print(f"\n{r['symbol']} ({r['score']}):")
        for line in r["rationale"][:14]:
            print(f"   - {line}")
    print("\n--- COMPONENTS ---")
    for r in results:
        c = r["comps"]
        print(f"  {r['symbol']}: " + " ".join(f"{k}={v}" for k, v in c.items()))
    with open("us_watchlist_results.json", "w") as f:
        json.dump(results, f, indent=2, default=str)


if __name__ == "__main__":
    main()
