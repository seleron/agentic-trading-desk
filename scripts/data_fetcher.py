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
import hashlib
import json
import logging
import os
import shutil
import sys
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Retry with exponential backoff
# ---------------------------------------------------------------------------

def _retry_with_backoff(
    func,
    retries: int = 3,
    backoffs: tuple[float, ...] | None = None,
    retryable_exceptions: tuple[type[Exception], ...] | None = None,
) -> object:
    """
    Call *func()* up to *retries* times with exponential backoff between attempts.

    Args:
        func: Zero-argument callable that returns the desired result.
        retries: Max number of attempts (1 = call once, no retry).
        backoffs: Seconds to wait before each retry attempt.  Defaults to
                  ``(1.0, 3.0, 9.0)`` — i.e. 3 total attempts with 1 s / 3 s delays.
        retryable_exceptions: Exception types that trigger a retry.  Defaults
                              to connection-related errors only.

    Returns:
        The return value of *func* on success.

    Raises:
        The last exception if all retries are exhausted.
    """
    if backoffs is None:
        backoffs = (1.0, 3.0, 9.0)
    if retryable_exceptions is None:
        # Broad but not everything — we don't want to retry ValueErrors from bad symbols.
        retryable_exceptions = (
            ConnectionError,
            TimeoutError,
            OSError,
            RuntimeError,  # ccxt sometimes raises this for network issues
        )

    last_exc: Optional[Exception] = None
    for attempt in range(1, retries + 1):
        try:
            return func()
        except retryable_exceptions as exc:
            last_exc = exc
            if attempt < retries:
                delay = backoffs[min(attempt - 1, len(backoffs) - 1)]
                logger.warning(
                    "Connection error fetching data (attempt %d/%d): %s — retrying in %.1fs",
                    attempt,
                    retries,
                    exc,
                    delay,
                )
                time.sleep(delay)

    raise last_exc  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Local JSON cache
# ---------------------------------------------------------------------------

def _cache_dir() -> Path:
    """Return the cache directory (~/.cache/agentic-trading-desk/), creating it if needed."""
    d = Path.home() / ".cache" / "agentic-trading-desk"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _cache_key(exchange: str, symbol: str, timeframe: str) -> str:
    """Deterministic cache key from exchange + symbol + timeframe."""
    raw = f"{exchange}:{symbol}:{timeframe}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def _cache_path(exchange: str, symbol: str, timeframe: str) -> Path:
    """Full path to the cached JSON file for a given request."""
    return _cache_dir() / f"{_cache_key(exchange, symbol, timeframe)}.json"


def get_cached_data(
    exchange: str,
    symbol: str,
    timeframe: str,
    ttl_seconds: int | None = None,
) -> list[dict] | None:
    """
    Load cached OHLCV data if it exists and is still valid.

    Args:
        exchange: Exchange name (e.g., 'mexc', 'binance').
        symbol: Trading pair (e.g., 'THYAO/TRY').
        timeframe: Candle timeframe ('1d', '4h', etc.).
        ttl_seconds: Cache TTL in seconds.  Defaults to 300 (5 min).

    Returns:
        Cached list of OHLCV dicts, or ``None`` if no valid cache entry exists.
    """
    cache_file = _cache_path(exchange, symbol, timeframe)
    if not cache_file.exists():
        return None

    try:
        stat = cache_file.stat()
        age = time.time() - stat.st_mtime
        ttl = ttl_seconds if ttl_seconds is not None else 300
        if age > ttl:
            logger.info("Cache expired for %s/%s (%.0fs old, TTL=%ds)", symbol, timeframe, age, ttl)
            cache_file.unlink(missing_ok=True)
            return None

        with open(cache_file) as f:
            data = json.load(f)
        # Validate structure quickly
        if isinstance(data, list) and len(data) > 0 and "close" in data[0]:
            logger.debug("Cache hit for %s/%s", symbol, timeframe)
            return data
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("Corrupt cache file %s: %s — discarding", cache_file.name, exc)
        cache_file.unlink(missing_ok=True)

    return None


def save_cached_data(
    exchange: str,
    symbol: str,
    timeframe: str,
    data: list[dict],
) -> None:
    """Write OHLCV data to the local JSON cache."""
    cache_file = _cache_path(exchange, symbol, timeframe)
    try:
        with open(cache_file, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except OSError as exc:
        logger.warning("Failed to write cache for %s/%s: %s", symbol, timeframe, exc)


# ---------------------------------------------------------------------------
# Gap detection
# ---------------------------------------------------------------------------

def detect_gaps(ohlcv_data: list[dict], max_gap_seconds: float = 86400.0) -> list[str]:
    """
    Scan OHLCV data for gaps between consecutive bars.

    Args:
        ohlcv_data: List of dicts with at least a ``datetime`` key (ISO-8601 string).
        max_gap_seconds: Maximum acceptable seconds between consecutive bars before
                         a gap is reported.  Defaults to one day (86400 s).

    Returns:
        List of warning strings for each detected gap.  Empty list means no gaps.
    """
    warnings: list[str] = []
    if len(ohlcv_data) < 2:
        return warnings

    import datetime as _dt

    prev_dt = None
    for candle in ohlcv_data:
        ts_str = candle.get("datetime") or candle.get("timestamp")
        if ts_str is None:
            continue

        try:
            if isinstance(ts_str, str):
                # Handle ISO-8601 strings (strip trailing Z, handle timezone)
                dt = _dt.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
            elif isinstance(ts_str, (int, float)):
                dt = _dt.datetime.fromtimestamp(ts_str, tz=_dt.timezone.utc)
            else:
                continue

            if prev_dt is not None:
                delta = abs((dt - prev_dt).total_seconds())
                if delta > max_gap_seconds:
                    gap_hours = round(delta / 3600, 1)
                    warnings.append(
                        f"OHLCV gap detected between {prev_dt.isoformat()} and "
                        f"{dt.isoformat()} ({gap_hours}h — expected ~{max_gap_seconds/3600:.0f}h)"
                    )

            prev_dt = dt
        except (ValueError, OverflowError) as exc:
            logger.debug("Could not parse datetime %s for gap check: %s", ts_str, exc)

    return warnings


# ---------------------------------------------------------------------------
# Public API — fetch_ohlcv (wraps ccxt with retry + cache)
# ---------------------------------------------------------------------------

def fetch_ohlcv(
    exchange_name: str,
    symbol: str,
    timeframe: str = "1d",
    limit: int = 200,
    use_cache: bool = True,
    ttl_seconds: int | None = None,
) -> list[dict]:
    """
    Fetch OHLCV data from a ccxt exchange with retry logic and optional caching.

    Args:
        exchange_name: Exchange ID (e.g., 'binance', 'coinbase', 'kraken')
        symbol: Trading pair in ccxt format (e.g., 'BTC/USDT')
        timeframe: Candle timeframe ('1m', '5m', '15m', '1h', '4h', '1d', etc.)
        limit: Number of candles to fetch
        use_cache: If True, check local JSON cache before fetching.  Default ``True``.
        ttl_seconds: Cache time-to-live in seconds.  Overrides the global default (5 min).

    Returns:
        List of dicts with keys: timestamp, datetime, open, high, low, close, volume

    Note:
        The public API is unchanged from the original — callers do not need to know
        about retry or cache parameters; they are optional keyword arguments.
     """
    import ccxt

    effective_ttl = ttl_seconds if ttl_seconds is not None else 300

    exchange_class = getattr(ccxt, exchange_name.lower(), None)
    if exchange_class is None:
        raise ValueError(f"Unknown exchange: {exchange_name}. Available: {ccxt.exchanges}")

    # ---- Check cache first (if enabled) ----
    if use_cache:
        cached = get_cached_data(exchange_name, symbol, timeframe, ttl_seconds=effective_ttl)
        if cached is not None:
            return cached

    # ---- Fetch with retry + backoff ----
    exchange = exchange_class({
        "enableRateLimit": True,
    })

    def _do_fetch():
        return exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)

    ohlcv_raw = _retry_with_backoff(_do_fetch, retries=3, backoffs=(1.0, 3.0, 9.0))

    result = [
        {
            "timestamp": int(c[0]),
            "datetime": exchange.iso8601(c[0]) if c[0] else None,
            "open": float(c[1]),
            "high": float(c[2]),
            "low": float(c[3]),
            "close": float(c[4]),
            "volume": float(c[5]),
        }
        for c in ohlcv_raw
    ]

    # ---- Gap detection ----
    gaps = detect_gaps(result)
    if gaps:
        for gap_msg in gaps:
            logger.warning("data_fetcher: %s", gap_msg)

    # ---- Save to cache (if enabled) ----
    if use_cache and result:
        save_cached_data(exchange_name, symbol, timeframe, result)

    return result


# Default TTL constant for modules that import it.
DEFAULT_CACHE_TTL = 300  # seconds — 5 minutes


# ---------------------------------------------------------------------------
# Public API — fetch_etf_series (unchanged signature)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public API — fetch_macro_series (unchanged signature)
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# Public API — fetch_bist_data (unchanged signature)
# ---------------------------------------------------------------------------

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

    Note:
        Internally this function now uses retry logic (up to 3 attempts with
        exponential backoff) and local caching.  The public API is unchanged —
        callers receive the same list-of-dicts format.
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


# ---------------------------------------------------------------------------
# CLI entry point (unchanged)
# ---------------------------------------------------------------------------

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
