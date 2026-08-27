#!/usr/bin/env python3
"""
test_unified_data_provider.py
=============================
Offline tests for unified_data_provider routing (no network, no API keys).

Verifies the post-review data layer:
  * BIST symbols (.IS) route through yfinance's .IS Ticker — borsapy is gone.
  * yfinance is actually installed in the loop env (so the BIST path can run).
  * Normalized OHLCV bars keep their key set and are sorted ascending by date.

Run with:  python3 scripts/test_unified_data_provider.py
(uses unittest + unittest.mock — no external network calls.)
"""
from __future__ import annotations

import datetime
import math
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------
sys.path.insert(0, str(Path(__file__).resolve().parent))
import unified_data_provider as udp


def _make_hist_df(n: int, start: datetime.date = datetime.date(2024, 1, 1)):
    """Build a minimal yfinance-style DataFrame for the .IS fetcher to chew on."""
    import pandas as pd

    rows = []
    for i in range(n):
        d = start + datetime.timedelta(days=i)
        base = 100.0 + i
        rows.append({
            "Open": base,
            "High": base * 1.01,
            "Low": base * 0.99,
            "Close": base * 1.005,
            "Volume": 1_000_000 + i,
        })
    idx = pd.date_range(start=start, periods=n, freq="D")
    return pd.DataFrame(rows, index=idx)


def _fake_yf_module(df):
    """Return a stand-in yfinance module whose Ticker returns `df` from history()."""
    mod = MagicMock(name="yfinance")
    tick = MagicMock(name="Ticker")
    tick.history.return_value = df
    mod.Ticker.return_value = tick
    return mod


# ===================================================================
# 1. yfinance is present in the loop environment (BIST path can run)
# ===================================================================
class TestYfinanceAvailable(unittest.TestCase):
    """The BIST route now depends on yfinance — it must be importable here."""

    def test_yfinance_installed(self):
        self.assertIsNotNone(
            udp._yf,
            "yfinance is imported as _yf at module load; it should be present "
            "in the loop environment (worktree-setup.sh reports it importable).",
        )


# ===================================================================
# 2. BIST (.IS) routes through yfinance .IS — borsapy is gone
# ===================================================================
class TestBistRoutesToYfinance(unittest.TestCase):
    """fetch_stock_data('X.IS') must call yfinance Ticker('X.IS').history()."""

    def test_bist_symbol_hits_yfinance_is_ticker(self):
        df = _make_hist_df(120)
        fake_yf = _fake_yf_module(df)
        with patch.object(udp, "_yf", fake_yf):
            out = udp.fetch_stock_data("EREGL.IS", days=60)

        # yfinance.Ticker was constructed with the .IS symbol verbatim
        fake_yf.Ticker.assert_called_once_with("EREGL.IS")
        self.assertIsNotNone(out, "expected bars for a .IS symbol")
        self.assertGreaterEqual(len(out), 20, "expected a non-trivial bar count")

    def test_bist_does_not_require_finnhub(self):
        """BIST path is independent of finnhub (even when finnhub is absent)."""
        df = _make_hist_df(120)
        fake_yf = _fake_yf_module(df)
        with patch.object(udp, "_yf", fake_yf), \
             patch.object(udp, "finnhub", None):
            out = udp.fetch_stock_data("THYAO.IS", days=60)
        self.assertIsNotNone(out)

    def test_bist_bars_normalized_and_sorted(self):
        df = _make_hist_df(60)
        fake_yf = _fake_yf_module(df)
        with patch.object(udp, "_yf", fake_yf):
            out = udp.fetch_stock_data("TUPRS.IS", days=60)

        self.assertIsNotNone(out)
        required = {"date", "open", "high", "low", "close", "volume"}
        for bar in out:
            self.assertTrue(required.issubset(bar.keys()), f"bar missing keys: {bar}")
            self.assertIsInstance(bar["close"], float)
            self.assertIsInstance(bar["volume"], int)
        # Dates strictly ascending after sort
        dates = [bar["date"] for bar in out]
        self.assertEqual(dates, sorted(dates))

    def test_bist_truncates_to_days(self):
        df = _make_hist_df(200)
        fake_yf = _fake_yf_module(df)
        with patch.object(udp, "_yf", fake_yf):
            out = udp.fetch_stock_data("ASELS.IS", days=50)
        self.assertEqual(len(out), 50)

    def test_bist_empty_history_returns_none(self):
        import pandas as pd
        empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        fake_yf = _fake_yf_module(empty)
        with patch.object(udp, "_yf", fake_yf):
            out = udp.fetch_stock_data("GARAN.IS", days=60)
        self.assertIsNone(out)

    def test_bist_nan_row_skipped(self):
        df = _make_hist_df(120)
        # Poison one row with NaN so the fetcher must skip it
        df.iloc[5, df.columns.get_loc("Close")] = math.nan
        fake_yf = _fake_yf_module(df)
        with patch.object(udp, "_yf", fake_yf):
            out = udp.fetch_stock_data("AKBNK.IS", days=120)
        self.assertIsNotNone(out)
        # One NaN row dropped -> fewer bars than source
        self.assertEqual(len(out), 119)


# ===================================================================
# 3. borsapy is fully retired from the module
# ===================================================================
class TestBorsapyRetired(unittest.TestCase):
    """No borsapy import or _fetch_borsapy path should remain in the provider."""

    def test_no_borsapy_attribute(self):
        self.assertFalse(
            hasattr(udp, "_bt"),
            "module should no longer expose the borsapy _bt handle",
        )

    def test_no_fetch_borsapy_function(self):
        self.assertFalse(
            hasattr(udp, "_fetch_borsapy"),
            "_fetch_borsapy should be gone; BIST now uses _fetch_yfinance_bist",
        )

    def test_new_bist_fetcher_present(self):
        self.assertTrue(
            hasattr(udp, "_fetch_yfinance_bist"),
            "expected the new _fetch_yfinance_bist helper to exist",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
