#!/usr/bin/env python3
"""
data_fetcher.py
===============
Universal data fetcher using ccxt for multi-exchange support.
Replaces Robinhood MCP as the primary data source.

Supported exchanges: Binance, Coinbase, Kraken, Bybit, OKX, and any ccxt-supported exchange.
Also supports BIST (Borsa Istanbul) via ccxt's `mexc` or direct connector patterns.

Usage:
    python3 scripts/data_fetcher.py BINANCE BTC/USDT 1d 200 --json
    python3 scripts/data_fetcher.py BYBIT ETH/USDT 4h 100
    python3 scripts/data_fetcher.py --help

Stdlib only. ccxt is the only external dependency (pip install ccxt).
"""
from __future__ import annotations

import argparse
import json
import sys
from typing import Optional


def fetch_ohlcv(
    exchange_name: str,
    symbol: str,
    timeframe: str = "1d",
    limit: int = 200,
) -> list[dict]:
    """
    Fetch OHLCV data from a ccxt exchange.

    Args:
        exchange_name: Exchange ID (e.g., 'binance', 'coinbase', 'kraken')
        symbol: Trading pair in ccxt format (e.g., 'BTC/USDT')
        timeframe: Candle timeframe ('1m', '5m', '15m', '1h', '4h', '1d', etc.)
        limit: Number of candles to fetch

    Returns:
        List of dicts with keys: timestamp, datetime, open, high, low, close, volume
    """
    import ccxt

    exchange_class = getattr(ccxt, exchange_name, None)
    if exchange_class is None:
        raise ValueError(f"Unknown exchange: {exchange_name}. Available: {ccxt.exchanges}")

    exchange = exchange_class({
        "enableRateLimit": True,
    })

    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    return [
        {
            "timestamp": int(c[0]),
            "datetime": exchange.iso8601(c[0]) if c[0] else None,
            "open": c[1],
            "high": c[2],
            "low": c[3],
            "close": c[4],
            "volume": c[5],
        }
        for c in ohlcv
    ]


def fetch_etf_series(
    exchange_name: str,
    symbols: list[str],
    timeframe: str = "1d",
    limit: int = 300,
) -> dict[str, list[float]]:
    """
    Fetch close price series for multiple ETF symbols.

    Args:
        exchange_name: Exchange ID
        symbols: List of ccxt-formatted symbol strings
        timeframe: Candle timeframe
        limit: Candles per symbol

    Returns:
        Dict mapping symbol -> list of close prices (oldest first)
    """
    result = {}
    for sym in symbols:
        try:
            data = fetch_ohlcv(exchange_name, sym, timeframe, limit)
            if not data:
                continue
            closes = [c["close"] for c in data]
            result[sym] = closes
        except Exception as e:
            print(f"[WARN] Failed to fetch {sym}: {e}", file=sys.stderr)

    return result


def fetch_macro_series(
    exchange_name: str = "binance",
    timeframe: str = "1d",
    limit: int = 300,
) -> dict:
    """
    Fetch all macro sentiment ETF series in ccxt format.

    Maps traditional ticker symbols to crypto pairs on supported exchanges.
    For BIST support, uses direct API or fallback.

    Returns data structure compatible with macro_pillar.py.
    """
    # Map traditional tickers to exchange symbols (varies by exchange)
    symbol_map = {
        "SPY": "SPY/USD",
        "RSP": "RSP/USD",
        "IWM": "IWM/USD",
        "HYG": "HYG/USD",
        "LQD": "LQD/USD",
        "TLT": "TLT/USD",
        "XLY": "XLY/USD",
        "XLP": "XLP/USD",
    }

    series = fetch_etf_series(exchange_name, list(symbol_map.values()), timeframe, limit)

    # Re-key to traditional ticker names for macro_pillar.py compatibility
    result = {"series": {}}
    for orig_ticker, ccxt_sym in symbol_map.items():
        if ccxt_sym in series:
            result["series"][orig_ticker] = series[ccxt_sym]

    return result


def fetch_bist_data(
    symbol: str,
    timeframe: str = "1d",
    limit: int = 300,
) -> list[dict]:
    """
    Fetch data for BIST (Borsa Istanbul) stocks.

    Uses ccxt's Mexc exchange which lists many Turkish stocks,
    or falls back to direct API patterns.

    Args:
        symbol: BIST ticker (e.g., 'THYAO', 'GARAN', 'ASELS')
        timeframe: Candle timeframe
        limit: Number of candles

    Returns:
        List of OHLCV dicts compatible with indicators.py
    """
    import ccxt

    # Try multiple exchanges that support Turkish stocks
    for exchange_name in ["mexc", "binance"]:
        try:
            data = fetch_ohlcv(exchange_name, f"{symbol}/TRY", timeframe, limit)
            if data:
                return data
        except Exception as e:
            print(f"[WARN] {exchange_name} failed for {symbol}: {e}", file=sys.stderr)

    # Fallback: try Binance USDT pairs
    try:
        data = fetch_ohlcv("binance", f"{symbol}/USDT", timeframe, limit)
        if data:
            return data
    except Exception as e:
        print(f"[WARN] binance {symbol}/USDT failed: {e}", file=sys.stderr)

    raise ValueError(f"No exchange has data for BIST symbol: {symbol}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Universal data fetcher via ccxt (multi-exchange)."
    )
    ap.add_argument("exchange", help="Exchange name (e.g., binance, coinbase, kraken)")
    ap.add_argument("symbol", help="Trading pair in ccxt format (e.g., BTC/USDT, THYAO/TRY)")
    ap.add_argument(
        "timeframe", default="1d", help="Candle timeframe (default: 1d)"
    )
    ap.add_argument("--limit", type=int, default=200, help="Number of candles")
    ap.add_argument(
        "--json", action="store_true", help="Output in JSON format"
    )
    ap.add_argument(
        "--macro", action="store_true", help="Fetch all macro ETF series"
    )
    args = ap.parse_args()

    try:
        if args.macro:
            data = fetch_macro_series(args.exchange, args.timeframe, args.limit)
        else:
            data = fetch_ohlcv(
                args.exchange, args.symbol, args.timeframe, args.limit
            )
            data = {"symbol": args.symbol, "timeframe": args.timeframe, "candles": data}

        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0
    except Exception as e:
        error_data = {"error": str(e), "exchange": args.exchange, "symbol": args.symbol}
        print(json.dumps(error_data, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
