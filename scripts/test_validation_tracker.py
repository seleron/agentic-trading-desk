#!/usr/bin/env python3
"""
test_validation_tracker.py
==========================
Tests for the daily validation tracker module.

Covers: SQLite schema, morning snapshot recording, EOD actuals with delta
computation, prediction correctness logic, report generation, and edge cases.

Run with:  python3 scripts/test_validation_tracker.py   (unittest — no external deps)
"""
from __future__ import annotations

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Import the module under test — use a local alias to avoid name collision.
import validation_tracker as vt


def _make_mock_yfinance():
    """Create mock yfinance.Ticker that returns fake OHLCV data."""
    mock_ticker = MagicMock()
    mock_hist = MagicMock()
    # Create a DataFrame-like object with index and iloc
    import pandas

    mock_hist.index = [pandas.Timestamp("2026-07-10")]
    mock_hist.iloc = MagicMock(return_value=pandas.Series({
        "Close": 42.5,
        "Open": 42.0,
        "High": 43.0,
        "Low": 41.8,
        "Volume": 1_500_000,
    }))
    mock_ticker.history = MagicMock(return_value=mock_hist)
    return mock_ticker


class TestSQLiteInit(unittest.TestCase):
    """Verify database initialization creates all required tables and indexes."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_tables_created(self):
        """init_db should create morning_snapshots, eod_actuals, weekly_summaries."""
        conn = vt.init_db(self.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name IN (?, ?, ?)",
            ("morning_snapshots", "eod_actuals", "weekly_summaries"),
        )
        tables = {row[0] for row in cursor.fetchall()}
        conn.close()
        self.assertEqual(tables, {"morning_snapshots", "eod_actuals", "weekly_summaries"})

    def test_indexes_created(self):
        """Unique indexes on (date, symbol) should exist."""
        conn = vt.init_db(self.db_path)
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND sql LIKE '%UNIQUE%'"
        )
        indexes = {row[0] for row in cursor.fetchall()}
        conn.close()
        self.assertTrue(any("idx_snapshots" in idx for idx in indexes))
        self.assertTrue(any("idx_eod" in idx for idx in indexes))


class TestRecordMorningScore(unittest.TestCase):
    """Test morning snapshot recording to SQLite."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_record_single_symbol(self):
        """A single morning snapshot should be recorded."""
        symbols_data = {
            "EREGL": {
                "score": 75.0,
                "decision": "BUY",
                "rsi": 62.0,
                "macd": 0.3,
                "ema20": 41.0,
                "ema50": 40.0,
                "ema200": 38.0,
                "close_price": 42.5,
                "rationale": ["EMA bullish stack"],
            }
        }
        records = vt.record_morning_score("2026-07-11", symbols_data, self.db_path)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["symbol"], "EREGL")
        self.assertEqual(records[0]["score"], 75.0)

    def test_record_multiple_symbols(self):
        """Multiple symbols should all be recorded."""
        symbols_data = {
            sym: {"score": 50.0, "decision": "HOLD", "close_price": 10.0}
            for sym in ["EREGL", "ASELS", "THYAO"]
        }
        records = vt.record_morning_score("2026-07-11", symbols_data, self.db_path)
        self.assertEqual(len(records), 3)

    def test_upsert_same_date_symbol(self):
        """Re-recording the same date+symbol should update (INSERT OR REPLACE)."""
        data = {"EREGL": {"score": 60.0, "close_price": 42.0}}
        vt.record_morning_score("2026-07-11", data, self.db_path)
        vt.record_morning_score("2026-07-11", {"EREGL": {"score": 80.0, "close_price": 43.0}}, self.db_path)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT score FROM morning_snapshots WHERE symbol = ? AND date = ?", ("EREGL", "2026-07-11"))
        row = cursor.fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertEqual(row[0], 80.0)  # updated, not duplicated


class TestRecordEodActuals(unittest.TestCase):
    """Test end-of-day actuals recording and delta computation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_delta_positive_with_high_score_correct(self):
        """Score >= 60 and price up → CORRECT."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 75.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 43.0, "open_price": 42.1, "high": 43.5}},
            self.db_path,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["accuracy_flag"], "CORRECT")
        self.assertTrue(records[0]["prediction_correct"])
        # delta should be positive
        self.assertGreater(records[0]["delta_pct"], 0)

    def test_delta_negative_with_high_score_incorrect(self):
        """Score >= 60 but price down → INCORRECT."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 75.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 41.0, "open_price": 41.5, "high": 42.0}},
            self.db_path,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["accuracy_flag"], "INCORRECT")
        self.assertFalse(records[0]["prediction_correct"])

    def test_delta_negative_with_low_score_correct(self):
        """Score < 60 and price down → CORRECT."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 45.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 41.0, "open_price": 41.5, "high": 42.0}},
            self.db_path,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["accuracy_flag"], "CORRECT")

    def test_delta_positive_with_low_score_incorrect(self):
        """Score < 60 but price up → INCORRECT."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 45.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 43.0, "open_price": 42.5, "high": 43.5}},
            self.db_path,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["accuracy_flag"], "INCORRECT")

    def test_no_morning_snapshot_skips_eod(self):
        """EOD without a morning snapshot should skip the symbol."""
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 43.0, "open_price": 42.5}},
            self.db_path,
        )
        self.assertEqual(len(records), 0)

    def test_delta_zero_with_high_score_incorrect(self):
        """Score >= 60 but price exactly flat (no change) → INCORRECT."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 75.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 42.0, "open_price": 42.0, "high": 42.5}},
            self.db_path,
        )
        self.assertEqual(len(records), 1)
        # price went up (42.0 > 42.0 is False, so INCORRECT for score >= 60)
        self.assertEqual(records[0]["accuracy_flag"], "INCORRECT")
        self.assertAlmostEqual(records[0]["delta_pct"], 0.0, places=3)

    def test_delta_zero_with_low_score_correct(self):
        """Score < 60 and price exactly flat → INCORRECT (price didn't go down)."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 45.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 42.0, "open_price": 42.0, "high": 42.5}},
            self.db_path,
        )
        self.assertEqual(len(records), 1)
        # price went down (42.0 < 42.0 is False) → INCORRECT
        self.assertEqual(records[0]["accuracy_flag"], "INCORRECT")

    def test_delta_calculation_precision(self):
        """Delta should be computed correctly with proper precision."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 50.0, "close_price": 100.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 103.0, "open_price": 101.0}},
            self.db_path,
        )
        expected_delta = round((103.0 - 100.0) / 100.0 * 100, 4)
        self.assertAlmostEqual(records[0]["delta_pct"], expected_delta, places=3)


class TestGenerateValidationReport(unittest.TestCase):
    """Test report generation from accumulated validation data."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _populate_data(self):
        """Create a small dataset for testing."""
        # Day 1: all correct
        vt.record_morning_score("2026-07-06", {
            "EREGL": {"score": 75.0, "close_price": 42.0},
        }, self.db_path)
        vt.record_eod_actuals("2026-07-06", {
            "EREGL": {"close_price": 43.0, "open_price": 42.1},
        }, self.db_path)

        # Day 2: incorrect (high score but price dropped)
        vt.record_morning_score("2026-07-07", {
            "EREGL": {"score": 80.0, "close_price": 43.0},
        }, self.db_path)
        vt.record_eod_actuals("2026-07-07", {
            "EREGL": {"close_price": 42.0, "open_price": 42.5},
        }, self.db_path)

    def test_report_with_data(self):
        """Report should contain accuracy stats when data exists."""
        self._populate_data()
        report = vt.generate_validation_report("2026-07-06", "2026-07-07", self.db_path)
        self.assertFalse(report.get("no_data"))
        self.assertEqual(report["total_predictions"], 2)
        self.assertEqual(report["correct_predictions"], 1)
        self.assertAlmostEqual(report["accuracy_pct"], 50.0, places=1)
        self.assertIn("symbol_accuracy", report)
        self.assertIn("EREGL", report["symbol_accuracy"])

    def test_report_no_data(self):
        """Report should indicate no data when range is empty."""
        report = vt.generate_validation_report("2026-07-01", "2026-07-05", self.db_path)
        self.assertTrue(report.get("no_data"))

    def test_report_stores_weekly_summary(self):
        """Report should persist a weekly summary to the DB."""
        self._populate_data()
        report = vt.generate_validation_report("2026-07-06", "2026-07-07", self.db_path)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute("SELECT COUNT(*) FROM weekly_summaries")
        count = cursor.fetchone()[0]
        conn.close()
        self.assertGreaterEqual(count, 1)


class TestPrepareMorningSnapshot(unittest.TestCase):
    """Test integration with scoring engine output format."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_convert_score_output(self):
        """score_quote output should be convertible to morning snapshots."""
        scored_quotes = [
            {
                "symbol": "EREGL",
                "score": 75.0,
                "raw_components": {"momentum": 12},
                "rationale": ["EMA bullish"],
            },
            {
                "symbol": "THYAO",
                "score": 35.0,
                "raw_components": {"momentum": 5},
                "rationale": ["Bearish MACD"],
            },
        ]

        records = vt.prepare_morning_snapshot("2026-07-11", scored_quotes, self.db_path)
        # Should have at least the symbols we passed in (may be more if yfinance data exists)
        symbols_found = {r["symbol"] for r in records}
        self.assertIn("EREGL", symbols_found)
        self.assertIn("THYAO", symbols_found)


class TestIsTradingDay(unittest.TestCase):
    """Verify weekday detection."""

    def test_weekday_is_trading_day(self):
        """Monday through Friday should return True."""
        # Monday, July 13 2026
        from datetime import date as _date
        self.assertTrue(vt._is_trading_day(_date(2026, 7, 13)))  # Mon
        self.assertTrue(vt._is_trading_day(_date(2026, 7, 14)))  # Tue
        self.assertTrue(vt._is_trading_day(_date(2026, 7, 15)))  # Wed
        self.assertTrue(vt._is_trading_day(_date(2026, 7, 16)))  # Thu
        self.assertTrue(vt._is_trading_day(_date(2026, 7, 17)))  # Fri

    def test_weekend_is_not_trading_day(self):
        """Saturday and Sunday should return False."""
        from datetime import date as _date
        self.assertFalse(vt._is_trading_day(_date(2026, 7, 18)))  # Sat
        self.assertFalse(vt._is_trading_day(_date(2026, 7, 19)))  # Sun


class TestGoogleSheetsIntegration(unittest.TestCase):
    """Test Google Sheets write with fallback."""

    def test_write_to_google_sheets_success(self):
        """When sheet_id and api_key are provided, _append_to_google_sheet should work."""
        rows = [["Date", "Symbol"], ["2026-07-11", "EREGL"]]
        mock_resp = MagicMock()
        mock_resp.status = 200

        with patch("validation_tracker.urllib") as mock_urllib:
            mock_urllib.request.urlopen.return_value.__enter__ = lambda s: mock_resp
            mock_urllib.request.urlopen.return_value.__exit__ = lambda s, *a: None
            result = vt._append_to_google_sheet("fake_sheet_id", rows, "fake_api_key")
            self.assertTrue(result)

    def test_write_to_google_sheets_failure(self):
        """When API fails, should return False."""
        rows = [["Date", "Symbol"]]

        with patch("validation_tracker.urllib") as mock_urllib:
            mock_urllib.request.urlopen.side_effect = Exception("network error")
            result = vt._append_to_google_sheet("fake_sheet_id", rows, "fake_api_key")
            self.assertFalse(result)

    def test_write_to_google_sheets_no_credentials(self):
        """Without sheet_id or api_key, should return False."""
        rows = [["Date", "Symbol"]]
        result = vt._append_to_google_sheet("", rows, "")
        self.assertFalse(result)


class TestConfigurableSymbols(unittest.TestCase):
    """Test that tracked symbols are configurable."""

    def test_default_symbols(self):
        """DEFAULT_SYMBOLS should contain expected BIST tickers."""
        expected = ["EREGL", "ASELS", "THYAO", "SISE", "ANHYT"]
        self.assertEqual(vt.DEFAULT_SYMBOLS, expected)


class TestEodActualsUpsert(unittest.TestCase):
    """Test EOD actuals upsert behavior."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_eod_upsert_same_date_symbol(self):
        """Re-recording EOD for same date+symbol should update."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 75.0, "close_price": 42.0}},
            self.db_path,
        )

        # First record
        vt.record_eod_actuals("2026-07-11", {
            "EREGL": {"close_price": 43.0},
        }, self.db_path)

        # Second record (should replace first)
        vt.record_eod_actuals("2026-07-11", {
            "EREGL": {"close_price": 44.0},
        }, self.db_path)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT close_price, delta_pct FROM eod_actuals WHERE symbol = ? AND date = ?",
            ("EREGL", "2026-07-11"),
        )
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        # Should be the updated close (44.0), not the first one (43.0)
        self.assertAlmostEqual(row[0], 44.0, places=3)


class TestRecordMorningScoreEdgeCases(unittest.TestCase):
    """Test edge cases in morning score recording."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_empty_symbols_data(self):
        """Empty symbols dict should return empty records list."""
        records = vt.record_morning_score("2026-07-11", {}, self.db_path)
        self.assertEqual(records, [])

    def test_none_close_price(self):
        """Close price of None/missing should be stored as NULL."""
        symbols_data = {
            "EREGL": {"score": 50.0, "close_price": None}
        }
        records = vt.record_morning_score("2026-07-11", symbols_data, self.db_path)
        self.assertEqual(len(records), 1)

    def test_rationale_serialization(self):
        """List rationale should be JSON-serialized in SQLite."""
        symbols_data = {
            "EREGL": {
                "score": 50.0,
                "rationale": ["point one", "point two"],
            }
        }
        vt.record_morning_score("2026-07-11", symbols_data, self.db_path)

        conn = sqlite3.connect(self.db_path)
        cursor = conn.execute(
            "SELECT rationale FROM morning_snapshots WHERE symbol = ?", ("EREGL",)
        )
        row = cursor.fetchone()
        conn.close()

        self.assertIsNotNone(row)
        # Should be a JSON string that can be parsed back to the list
        parsed = json.loads(row[0])
        self.assertEqual(parsed, ["point one", "point two"])


class TestEodActualsEdgeCases(unittest.TestCase):
    """Test edge cases in EOD actual recording."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_zero_morning_close(self):
        """Morning close of 0 should be skipped (division by zero protection)."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 50.0, "close_price": 0.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals("2026-07-11", {
            "EREGL": {"close_price": 43.0},
        }, self.db_path)
        self.assertEqual(len(records), 0)

    def test_missing_eod_close(self):
        """Missing EOD close should skip the symbol."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 50.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals("2026-07-11", {
            "EREGL": {},  # No close_price key
        }, self.db_path)
        self.assertEqual(len(records), 0)

    def test_multiple_symbols_mixed_results(self):
        """Some symbols correct, some incorrect — all should be recorded."""
        vt.record_morning_score("2026-07-11", {
            "EREGL": {"score": 80.0, "close_price": 42.0},
            "ASELS": {"score": 45.0, "close_price": 28.0},
        }, self.db_path)

        records = vt.record_eod_actuals("2026-07-11", {
            "EREGL": {"close_price": 43.0, "open_price": 42.5},   # up → CORRECT (score >= 60)
            "ASELS": {"close_price": 29.0, "open_price": 28.5},    # up → INCORRECT (score < 60)
        }, self.db_path)

        self.assertEqual(len(records), 2)
        flags = {r["symbol"]: r["accuracy_flag"] for r in records}
        self.assertEqual(flags["EREGL"], "CORRECT")
        self.assertEqual(flags["ASELS"], "INCORRECT")


class TestReportSymbolAccuracy(unittest.TestCase):
    """Test per-symbol accuracy tracking in reports."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_multi_symbol_accuracy_breakdown(self):
        """Report should contain per-symbol accuracy."""
        # Day 1: EREGL correct prediction (score >= 60, price up)
        vt.record_morning_score("2026-07-06", {
            "EREGL": {"score": 80.0, "close_price": 42.0},
        }, self.db_path)
        vt.record_eod_actuals("2026-07-06", {
            "EREGL": {"close_price": 43.0},
        }, self.db_path)

        # Day 1: ASELS correct prediction (score < 60, price down)
        vt.record_morning_score("2026-07-06", {
            "ASELS": {"score": 50.0, "close_price": 28.0},
        }, self.db_path)
        vt.record_eod_actuals("2026-07-06", {
            "ASELS": {"close_price": 27.0},
        }, self.db_path)

        # Day 2: EREGL correct (score >= 60, price up again)
        vt.record_morning_score("2026-07-07", {
            "EREGL": {"score": 80.0, "close_price": 43.0},
        }, self.db_path)
        vt.record_eod_actuals("2026-07-07", {
            "EREGL": {"close_price": 44.0},
        }, self.db_path)

        report = vt.generate_validation_report("2026-07-06", "2026-07-07", self.db_path)

        self.assertIn("EREGL", report["symbol_accuracy"])
        self.assertIn("ASELS", report["symbol_accuracy"])
        # EREGL: 100% accuracy (2/2 correct in this range)
        self.assertEqual(report["symbol_accuracy"]["EREGL"]["accuracy_pct"], 100.0)
        # ASELS: 100% accuracy (1/1 correct)
        self.assertEqual(report["symbol_accuracy"]["ASELS"]["accuracy_pct"], 100.0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
