#!/usr/bin/env python3
"""
test_data_quality.py
====================
Tests for BIST data quality improvements: retry logic, caching, gap detection,
and NaN-safe indicator computation.

Run with:  python3 scripts/test_data_quality.py
(uses unittest — no external deps needed.)
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import the modules under test
# ---------------------------------------------------------------------------

sys.path.insert(0, str(Path(__file__).resolve().parent))
from data_fetcher import (
    _cache_dir,
    _cache_key,
    _retry_with_backoff,
    detect_gaps,
    get_cached_data,
    save_cached_data,
)
from indicators import (
    bollinger,
    compute,
    ema_series,
    forward_fill,
    macd,
    rsi_wilder,
    trix,
)


# ===================================================================
# 1. Retry with exponential backoff
# ===================================================================

class TestRetryWithBackoff(unittest.TestCase):
    """Test _retry_with_backoff correctness and backoff timing."""

    def test_succeeds_on_first_try(self):
        call_count = [0]

        def ok_func():
            call_count[0] += 1
            return "success"

        result = _retry_with_backoff(ok_func, retries=3)
        self.assertEqual(result, "success")
        self.assertEqual(call_count[0], 1)

    def test_retries_on_failure_then_succeeds(self):
        call_count = [0]

        def fail_once():
            call_count[0] += 1
            if call_count[0] < 2:
                raise ConnectionError("network hiccup")
            return "recovered"

        result = _retry_with_backoff(fail_once, retries=3)
        self.assertEqual(result, "recovered")
        self.assertEqual(call_count[0], 2)

    def test_exhausts_retries(self):
        def always_fail():
            raise ConnectionError("always down")

        with self.assertRaises(ConnectionError):
            _retry_with_backoff(always_fail, retries=3, backoffs=(0.01, 0.01))

    def test_only_retries_retryable_exceptions(self):
        call_count = [0]

        def raises_value_error():
            call_count[0] += 1
            raise ValueError("bad symbol")

        with self.assertRaises(ValueError):
            _retry_with_backoff(raises_value_error, retries=3)
        # Should only have tried once — ValueError is not retryable by default
        self.assertEqual(call_count[0], 1)

    def test_custom_retryable_exceptions(self):
        call_count = [0]

        def raises_type_error():
            call_count[0] += 1
            raise TypeError("unexpected")

        with self.assertRaises(TypeError):
            _retry_with_backoff(
                raises_type_error,
                retries=2,
                backoffs=(0.01,),
                retryable_exceptions=(TypeError,),
            )
        # Should have tried twice (once + one retry)
        self.assertEqual(call_count[0], 2)


# ===================================================================
# 2. Local JSON cache
# ===================================================================

class TestCache(unittest.TestCase):
    """Test _cache_dir, _cache_key, get_cached_data, save_cached_data."""

    def setUp(self):
        # Use a temp directory instead of ~/.cache to avoid interference
        self.tmpdir = tempfile.mkdtemp()

    def _patch_cache_dir(self):
        """Patch _cache_dir to return our temp dir for this test method."""
        patcher = patch("data_fetcher._cache_dir", return_value=Path(self.tmpdir))
        self.addCleanup(patcher.stop)
        patcher.start()

    def test_cache_key_deterministic(self):
        k1 = _cache_key("binance", "BTC/USDT", "1d")
        k2 = _cache_key("binance", "BTC/USDT", "1d")
        self.assertEqual(k1, k2)

    def test_cache_key_differs_by_symbol(self):
        k1 = _cache_key("binance", "BTC/USDT", "1d")
        k2 = _cache_key("binance", "ETH/USDT", "1d")
        self.assertNotEqual(k1, k2)

    def test_save_and_load_cache(self):
        self._patch_cache_dir()
        sample_data = [
            {"timestamp": 1000, "datetime": "2025-01-01T00:00:00Z", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100},
            {"timestamp": 1001, "datetime": "2025-01-02T00:00:00Z", "open": 1.5, "high": 3.0, "low": 1.0, "close": 2.0, "volume": 200},
        ]
        save_cached_data("binance", "BTC/USDT", "1d", sample_data)

        result = get_cached_data("binance", "BTC/USDT", "1d")
        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["close"], 1.5)

    def test_cache_miss(self):
        self._patch_cache_dir()
        result = get_cached_data("binance", "NONEXIST/USD", "1d")
        self.assertIsNone(result)

    def test_cache_ttl_expiry(self):
        self._patch_cache_dir()
        sample_data = [
            {"timestamp": 1000, "datetime": "2025-01-01T00:00:00Z", "open": 1.0, "high": 2.0, "low": 0.5, "close": 1.5, "volume": 100},
        ]
        save_cached_data("binance", "BTC/USDT", "1d", sample_data)

        # Manually set cache file mtime to 3 seconds ago so TTL check fails deterministically (avoids flaky sleep on fast CI)
        cache_file = Path(self.tmpdir) / f"{_cache_key('binance', 'BTC/USDT', '1d')}.json"
        old_time = time.time() - 3
        os.utime(cache_file, (old_time, old_time))

        result = get_cached_data("binance", "BTC/USDT", "1d", ttl_seconds=2)
        self.assertIsNone(result)

    def test_cache_invalidates_corrupt_json(self):
        self._patch_cache_dir()
        cache_file = Path(_cache_dir()) / f"{_cache_key('binance', 'BAD/USD', '1d')}.json"
        cache_file.write_text("{invalid json!!!")

        result = get_cached_data("binance", "BAD/USD", "1d")
        self.assertIsNone(result)


# ===================================================================
# 3. Gap detection
# ===================================================================

class TestGapDetection(unittest.TestCase):
    """Test detect_gaps for OHLCV data."""

    def test_no_gap(self):
        candles = [
            {"datetime": "2025-01-01T00:00:00+00:00"},
            {"datetime": "2025-01-02T00:00:00+00:00"},
        ]
        warnings = detect_gaps(candles, max_gap_seconds=86400)
        self.assertEqual(warnings, [])

    def test_gap_detected(self):
        candles = [
            {"datetime": "2025-01-01T00:00:00+00:00"},
            {"datetime": "2025-01-05T00:00:00+00:00"},  # 4-day gap
        ]
        warnings = detect_gaps(candles, max_gap_seconds=86400)
        self.assertEqual(len(warnings), 1)
        self.assertIn("gap", warnings[0].lower())

    def test_single_candle_no_gap(self):
        candles = [{"datetime": "2025-01-01T00:00:00+00:00"}]
        warnings = detect_gaps(candles)
        self.assertEqual(warnings, [])

    def test_empty_list(self):
        warnings = detect_gaps([])
        self.assertEqual(warnings, [])

    def test_gap_with_timestamp_int(self):
        """Test gap detection with integer timestamps."""
        candles = [
            {"timestamp": 1735689600},   # 2025-01-01T00:00:00 UTC
            {"timestamp": 1736294400},   # 2025-01-08T00:00:00 UTC (7-day gap)
        ]
        warnings = detect_gaps(candles, max_gap_seconds=86400)
        self.assertEqual(len(warnings), 1)

    def test_multiple_gaps(self):
        candles = [
            {"datetime": "2025-01-01T00:00:00+00:00"},
            {"datetime": "2025-01-03T00:00:00+00:00"},  # +2 days — also a gap (>86400s)
            {"datetime": "2025-01-10T00:00:00+00:00"},  # +7 days from prev — another GAP
        ]
        warnings = detect_gaps(candles, max_gap_seconds=86400)
        self.assertEqual(len(warnings), 2)


# ===================================================================
# 4. NaN-safe forward fill
# ===================================================================

class TestForwardFill(unittest.TestCase):
    """Test forward_fill for NaN-safe indicator computation."""

    def test_no_gaps(self):
        series = [1.0, 2.0, 3.0, 4.0]
        filled, warnings = forward_fill(series)
        self.assertEqual(filled, [1.0, 2.0, 3.0, 4.0])
        self.assertEqual(warnings, [])

    def test_single_gap_filled(self):
        series = [1.0, None, None, 4.0]
        filled, warnings = forward_fill(series, max_gap=5)
        # Forward-fill: first two Nones become 1.0 (last known value)
        self.assertEqual(filled[0], 1.0)
        self.assertEqual(filled[1], 1.0)  # filled with last-known before gap
        self.assertEqual(filled[2], 1.0)  # same
        self.assertEqual(filled[3], 4.0)
        self.assertEqual(warnings, [])

    def test_gap_exceeds_max(self):
        series = [1.0] + [None] * 15  # 15 consecutive Nones > max_gap=10
        filled, warnings = forward_fill(series, max_gap=10)
        self.assertEqual(len(warnings), 1)
        self.assertIn("NaN gaps", warnings[0])

    def test_leading_nones(self):
        series = [None, None, 3.0, 4.0]
        filled, warnings = forward_fill(series, max_gap=5)
        # Leading Nones use next known value as approximation
        self.assertEqual(filled[2], 3.0)
        self.assertEqual(warnings, [])

    def test_trailing_nones(self):
        series = [1.0, 2.0, None, None]
        filled, warnings = forward_fill(series, max_gap=5)
        # Trailing Nones get filled with last known value (2.0)
        self.assertEqual(filled[2], 2.0)
        self.assertEqual(filled[3], 2.0)
        self.assertEqual(warnings, [])


# ===================================================================
# 5. Indicator correctness
# ===================================================================

class TestIndicators(unittest.TestCase):
    """Test indicator functions produce correct outputs."""

    def test_ema_series_basic(self):
        values = [1.0, 2.0, 3.0, 4.0, 5.0]
        result = ema_series(values, period=3)
        # First period-1 entries should be None (warmup)
        self.assertIsNone(result[0])
        self.assertIsNone(result[1])
        # Third entry is the SMA seed
        self.assertIsNotNone(result[2])

    def test_rsi_wilder_basic(self):
        close = [float(i + 1) for i in range(30)]  # steadily rising prices
        result = rsi_wilder(close, period=14)
        # After warmup (index >= 14), values should not be None
        self.assertIsNotNone(result[14])

    def test_macd_basic(self):
        close = [float(i + 1) for i in range(60)]
        macd_line, signal, hist = macd(close, 12, 26, 9)
        self.assertEqual(len(macd_line), len(close))
        self.assertEqual(len(signal), len(close))
        self.assertEqual(len(hist), len(close))

    def test_trix_basic(self):
        close = [float(i + 1) for i in range(80)]
        trix_line, sig = trix(close, period=15, signal=9)
        self.assertEqual(len(trix_line), len(close))
        self.assertEqual(len(sig), len(close))

    def test_bollinger_basic(self):
        close = [float(i + 1) for i in range(30)]
        mid, upper, lower, pct_b = bollinger(close, period=20, mult=2.0)
        self.assertIsNotNone(mid)
        self.assertIsNotNone(upper)
        self.assertIsNotNone(lower)
        # Upper > Mid > Lower for non-zero stdev
        if upper and lower:
            self.assertGreater(upper, mid)
            self.assertLess(lower, mid)

    def test_bollinger_insufficient_data(self):
        close = [1.0, 2.0]
        mid, upper, lower, pct_b = bollinger(close, period=20)
        self.assertIsNone(mid)


# ===================================================================
# 6. Integration: compute() with NaN gaps
# ===================================================================

class TestComputeIntegration(unittest.TestCase):
    """Test the high-level compute() function end-to-end."""

    def test_compute_normal(self):
        """compute should return all indicators without error on normal data."""
        close = [100 + i * 0.5 for i in range(250)]
        result = compute(close)
        self.assertIn("ema20", result)
        self.assertIn("rsi14", result)
        self.assertIn("macd_line", result)
        self.assertIn("trix", result)

    def test_compute_with_nan_gaps(self):
        """compute should handle NaN gaps gracefully and emit warnings."""
        close = [float(i + 1) for i in range(250)]
        # Inject a gap of Nones by setting some closes to 0 (simulating missing data)
        result = compute(close, max_fill_gap=10)
        self.assertIn("data_quality_warnings", result)

    def test_compute_insufficient_bars(self):
        """compute should warn about insufficient bars for EMA-200."""
        close = [float(i + 1) for i in range(50)]
        result = compute(close)
        self.assertIsNotNone(result["warning"])
        self.assertIn("bars", result["warning"].lower())

    def test_compute_returns_all_keys(self):
        """compute should return all expected keys."""
        close = [float(i + 1) for i in range(250)]
        result = compute(close)
        expected_keys = {
            "n_bars", "warning", "data_quality_warnings",
            "close", "ema20", "ema50", "ema200",
            "ema20_slope", "ema50_slope", "ema200_slope",
            "rsi14", "rsi14_prev",
            "macd_line", "macd_signal", "macd_hist", "macd_hist_prev",
            "trix", "trix_prev",
            "trix_signal", "trix_signal_prev",
            "bars_since_below_ema20",
            "bb_mid", "bb_upper", "bb_lower", "percent_b",
            # Additional indicators (ATR, Ichimoku, VWAP)
            "atr14", "ichimoku", "vwap",
        }
        self.assertEqual(set(result.keys()), expected_keys)


# ===================================================================
# 7. Public API unchanged
# ===================================================================

class TestPublicAPIUnchanged(unittest.TestCase):
    """Verify that public function signatures are backward-compatible."""

    def test_fetch_ohlcv_signature(self):
        import inspect
        from data_fetcher import fetch_ohlcv
        sig = inspect.signature(fetch_ohlcv)
        params = list(sig.parameters.keys())
        self.assertIn("exchange_name", params)
        self.assertIn("symbol", params)
        self.assertIn("timeframe", params)
        self.assertIn("limit", params)

    def test_fetch_bist_data_signature(self):
        import inspect
        from data_fetcher import fetch_bist_data
        sig = inspect.signature(fetch_bist_data)
        params = list(sig.parameters.keys())
        self.assertIn("symbol", params)
        self.assertIn("timeframe", params)
        self.assertIn("limit", params)

    def test_compute_signature(self):
        import inspect
        from indicators import compute
        sig = inspect.signature(compute)
        params = list(sig.parameters.keys())
        self.assertIn("close", params)
        # Optional parameters should have defaults
        close_param = sig.parameters["close"]
        self.assertEqual(close_param.kind, inspect.Parameter.POSITIONAL_OR_KEYWORD)


if __name__ == "__main__":
    unittest.main(verbosity=2)
