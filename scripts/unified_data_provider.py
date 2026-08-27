#!/usr/bin/env python3
"""
unified_data_provider.py
========================
Unified data provider for the Agentic Trading Desk.

Routes requests to Finnhub (US stocks, yfinance fallback) or yfinance (BIST
stocks, .IS suffix).
Normalizes all output into a standard OHLCV format expected by scoring_engine.py:
  [ { "date": "YYYY-MM-DD", "open": float, ... }, ... ]

Usage:
    from unified_data_provider import fetch_stock_data
    data = fetch_stock_data("AAPL", days=730)        # US Stock -> Finnhub (fallback yfinance)
    data = fetch_stock_data("EREGL.IS", days=730)   # BIST Stock -> yfinance (.IS)
"""

from __future__ import annotations

import datetime
import math
import os
import sys
from typing import Optional

# Load environment variables from .env file if present
try:
    from dotenv import load_dotenv
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '.env')
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
except ImportError:
    pass

# Try importing optional dependencies
try:
    import finnhub
except ImportError:
    finnhub = None

try:
    import yfinance as _yf
except ImportError:
    _yf = None


def fetch_stock_data(symbol: str, days: int = 730) -> Optional[list[dict]]:
    """
    Fetch OHLCV data for a given symbol.
    
    Args:
        symbol: Stock ticker (e.g., 'AAPL' for US, 'EREGL.IS' for BIST).
        days: Number of historical days to fetch. Defaults to 730 (~2 years).

    Returns:
        A list of dicts with keys: date, open, high, low, close, volume.
        Returns None if data is insufficient or API fails.
    """
    symbol_upper = symbol.upper()
    
    # Detect Exchange Type
    is_bist = symbol_upper.endswith(".IS")

    try:
        if is_bist:
            # BIST routes through yfinance with the .IS suffix (borsapy was
            # removed as non-working; yfinance is the repo's established provider).
            return _fetch_yfinance_bist(symbol_upper, days)
        elif not is_bist and finnhub:
            data = _fetch_finnhub(symbol_upper, days)
            # Graceful fallback to mock data for testing when API key is missing/invalid
            if data is None:
                print(f"[INFO] {symbol}: using mock data (Finnhub unavailable)", file=sys.stderr)
                return get_mock_data(symbol_upper, days)
            return data
        else:
            print(f"[WARN] No provider available for {symbol} (BIST={is_bist})", file=sys.stderr)
            return None
    except Exception as e:
        print(f"[ERROR] Failed to fetch data for {symbol}: {e}", file=sys.stderr)
        return None


def _fetch_finnhub(symbol: str, days: int = 730) -> Optional[list[dict]]:
    """Fetch US stock data via Finnhub (with yfinance fallback for free tier)."""
    api_key = os.environ.get("FINNHUB_API_KEY")

    # Try Finnhub first (paid tier supports historical candles)
    if api_key and finnhub:
        client = finnhub.Client(api_key=api_key)
        
        end_date = datetime.datetime.utcnow()
        start_date = end_date - datetime.timedelta(days=days + 60)
        
        try:
            response = client.stock_candles(symbol, 'D', int(start_date.timestamp()), int(end_date.timestamp()))
            
            if response.get('s') == 'ok' and response.get('c'):
                closes = response['c']
                highs = response['h']
                lows = response['l']
                opens = response['o']
                volumes = response['v']
                timestamps = response['t']

                bars = []
                for i in range(len(closes)):
                    dt_obj = datetime.datetime.fromtimestamp(timestamps[i])
                    date_str = dt_obj.strftime("%Y-%m-%d")
                
                    c, h, l, o, v = closes[i], highs[i], lows[i], opens[i], volumes[i]
                
                    if math.isnan(c) or math.isnan(h) or math.isnan(l) or math.isnan(o):
                        continue
                    
                    bars.append({
                        "date": date_str,
                        "open": round(float(o), 4),
                        "high": round(float(h), 4),
                        "low": round(float(l), 4),
                        "close": round(float(c), 4),
                        "volume": int(v) if not math.isnan(v) else 0,
                    })

                bars.sort(key=lambda x: x['date'])
                return bars[-days:] if len(bars) > days else bars
                
        except (finnhub.FinnhubAPIException, Exception):
            pass  # Fall through to yfinance

    # Fallback: yfinance for US stocks (works on free tier)
    if _yf:
        try:
            ticker = _yf.Ticker(symbol.replace('.', '-'))  # NASDAQ uses dots in some cases
            hist = ticker.history(period=f"{days + 30}d")
        
            if hist.empty or len(hist) < 20:
                return None

            bars = []
            for date, row in hist.iterrows():
                dt_str = date.strftime("%Y-%m-%d")
                bars.append({
                    "date": dt_str,
                    "open": round(float(row['Open']), 4),
                    "high": round(float(row['High']), 4),
                    "low": round(float(row['Low']), 4),
                    "close": round(float(row['Close']), 4),
                    "volume": int(row['Volume']) if not math.isnan(row['Volume']) else 0,
                })

            return bars[-days:] if len(bars) > days else bars
        
        except Exception as e:
            print(f"[WARN] yfinance fallback failed for {symbol}: {e}", file=sys.stderr)
    
    return None


def _fetch_yfinance_bist(symbol: str, days: int = 730) -> Optional[list[dict]]:
    """Fetch BIST stock data via yfinance using the .IS suffix.

    Replaces the retired borsapy path — yfinance is the repo's established
    provider for BIST tickers (see us_watchlist_scan.py / watchlist_scan.py).
    """
    if not _yf:
        print(f"[WARN] yfinance not installed. Cannot fetch {symbol}.", file=sys.stderr)
        return None

    try:
        hist = _yf.Ticker(symbol).history(period=f"{days + 60}d", interval="1d", auto_adjust=True)

        if hist is None or hist.empty or len(hist) < 20:
            return None

        bars = []
        for dt, row in hist.iterrows():
            date_str = dt.strftime("%Y-%m-%d")

            o, h, l, c = float(row["Open"]), float(row["High"]), float(row["Low"]), float(row["Close"])

            if math.isnan(o) or math.isnan(h) or math.isnan(l) or math.isnan(c):
                continue

            bars.append({
                "date": date_str,
                "open": round(o, 4),
                "high": round(h, 4),
                "low": round(l, 4),
                "close": round(c, 4),
                "volume": int(row["Volume"]) if not math.isnan(row["Volume"]) else 0,
            })

        bars.sort(key=lambda x: x["date"])
        return bars[-days:] if len(bars) > days else bars

    except Exception as e:
        print(f"[WARN] yfinance BIST fetch failed for {symbol}: {e}", file=sys.stderr)
        return None


# --- Mock Data for Testing/Dev (Optional) ---
def get_mock_data(symbol: str, count: int = 200) -> Optional[list[dict]]:
    """Generate mock OHLCV data if APIs are down or keys missing."""
    import random
    price = 100.0
    bars = []
    base_date = datetime.date.today() - datetime.timedelta(days=count + 10)
    
    for i in range(count):
        d = base_date + datetime.timedelta(days=i+1)
        o = round(price * (1 + random.uniform(-0.02, 0.02)), 4)
        c = round(o * (1 + random.uniform(-0.02, 0.02)), 4)
        bars.append({
            "date": d.strftime("%Y-%m-%d"),
            "open": o,
            "high": max(o, c) * 1.01,
            "low": min(o, c) * 0.99,
            "close": c,
            "volume": int(random.uniform(1e6, 1e7)),
        })
        price = c
        
    return bars

if __name__ == "__main__":
    print("Testing Unified Data Provider...")
    
    # Test BIST (yfinance .IS)
    print("\n--- Testing BIST: EREGL.IS ---")
    bist_data = fetch_stock_data("EREGL.IS", days=100)
    if bist_data:
        print(f"  Fetched {len(bist_data)} bars. Latest: {bist_data[-1]}")
    else:
        print("  Failed to fetch BIST data.")

    # Test US (requires Finnhub key or yfinance fallback)
    print("\n--- Testing US: AAPL ---")
    us_data = fetch_stock_data("AAPL", days=100)
    if us_data:
        print(f"  Fetched {len(us_data)} bars. Latest: {us_data[-1]}")
    else:
        print("  Failed to fetch US data.")
