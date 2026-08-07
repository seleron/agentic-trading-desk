#!/usr/bin/env python3
"""
test_validation_tracker.py
==========================
Tests for the daily validation tracker module.

Covers: SQLite schema, morning snapshot recording, EOD actuals with delta
computation, prediction correctness logic (BUY/SELL/HOLD bands), report generation,
and edge cases.

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
        """Score >= 60 (BUY) and price up → CORRECT."""
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
        """Score >= 60 (BUY) but price down → INCORRECT."""
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
        """Score < 40 (SELL) and price down → CORRECT."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 35.0, "close_price": 42.0}},
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
        """Score < 40 (SELL) but price up → INCORRECT."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 35.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 43.0, "open_price": 42.5, "high": 43.5}},
            self.db_path,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["accuracy_flag"], "INCORRECT")

    def test_hold_score_neutral(self):
        """Score in HOLD range (40–59) → NEUTRAL, excluded from correctness."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 50.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 43.0, "open_price": 42.5, "high": 43.5}},
            self.db_path,
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["accuracy_flag"], "NEUTRAL")
        self.assertIsNone(records[0]["prediction_correct"])

    def test_hold_score_neutral_price_down(self):
        """Score in HOLD range (40–59) → NEUTRAL even when price drops."""
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
        self.assertEqual(records[0]["accuracy_flag"], "NEUTRAL")

    def test_no_morning_snapshot_skips_eod(self):
        """EOD without a morning snapshot should skip the symbol."""
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 43.0, "open_price": 42.5}},
            self.db_path,
        )
        self.assertEqual(len(records), 0)

    def test_delta_zero_with_high_score_incorrect(self):
        """Score >= 60 (BUY) but price exactly flat → INCORRECT."""
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
        # BUY expects up; flat price is not up → INCORRECT
        self.assertEqual(records[0]["accuracy_flag"], "INCORRECT")
        self.assertAlmostEqual(records[0]["delta_pct"], 0.0, places=3)

    def test_delta_zero_with_low_score_incorrect(self):
        """Score < 40 (SELL) and price exactly flat → INCORRECT."""
        vt.record_morning_score(
            "2026-07-11",
            {"EREGL": {"score": 35.0, "close_price": 42.0}},
            self.db_path,
        )
        records = vt.record_eod_actuals(
            "2026-07-11",
            {"EREGL": {"close_price": 42.0, "open_price": 42.0, "high": 42.5}},
            self.db_path,
        )
        self.assertEqual(len(records), 1)
        # SELL expects down; flat price is not down → INCORRECT
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
        # Day 1: BUY correct
        vt.record_morning_score("2026-07-06", {
            "EREGL": {"score": 75.0, "close_price": 42.0},
        }, self.db_path)
        vt.record_eod_actuals("2026-07-06", {
            "EREGL": {"close_price": 43.0, "open_price": 42.1},
        }, self.db_path)

        # Day 2: BUY incorrect (price dropped)
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

    def test_hold_excluded_from_accuracy(self):
        """HOLD (NEUTRAL) signals should be excluded from accuracy stats."""
        # Day 1: BUY correct + HOLD neutral
        vt.record_morning_score("2026-07-06", {
            "EREGL": {"score": 75.0, "close_price": 42.0},
            "ASELS": {"score": 50.0, "close_price": 28.0},
        }, self.db_path)
        vt.record_eod_actuals("2026-07-06", {
            "EREGL": {"close_price": 43.0, "open_price": 42.1},
            "ASELS": {"close_price": 29.0, "open_price": 28.5},
        }, self.db_path)

        report = vt.generate_validation_report("2026-07-06", "2026-07-06", self.db_path)
        # Only EREGL (BUY correct) counts; ASELS (HOLD/NEUTRAL) excluded
        self.assertEqual(report["total_predictions"], 1)
        self.assertEqual(report["correct_predictions"], 1)
        self.assertAlmostEqual(report["accuracy_pct"], 100.0, places=1)

    def test_report_mixed_buy_sell_neutral(self):
        """Mixed BUY/SELL/HOLD results: only directional ones count."""
        # EREGL: BUY correct, ASELS: SELL incorrect, THYAO: HOLD neutral
        vt.record_morning_score("2026-07-06", {
            "EREGL": {"score": 80.0, "close_price": 42.0},
            "ASELS": {"score": 30.0, "close_price": 28.0},
            "THYAO": {"score": 55.0, "close_price": 280.0},
        }, self.db_path)
        vt.record_eod_actuals("2026-07-06", {
            "EREGL": {"close_price": 43.0, "open_price": 42.1},   # BUY correct (up)
            "ASELS": {"close_price": 29.0, "open_price": 28.5},    # SELL incorrect (up)
            "THYAO": {"close_price": 278.0, "open_price": 279.0},  # HOLD neutral (down, but NEUTRAL)
        }, self.db_path)

        report = vt.generate_validation_report("2026-07-06", "2026-07-06", self.db_path)
        # Only EREGL and ASELS count; THYAO excluded
        self.assertEqual(report["total_predictions"], 2)
        self.assertEqual(report["correct_predictions"], 1)
        self.assertAlmostEqual(report["accuracy_pct"], 50.0, places=1)


class TestPrepareMorningSnapshot(unittest.TestCase):
    """Test integration with scoring engine output format."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.tmpdir, "validation.db")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    @patch("validation_tracker._get_morning_closes")
    def test_convert_score_output(self, mock_get_morning):
        """scored quotes list should be convertible to morning snapshots."""
        # Mock _get_morning_closes to bypass the date hard-guard (tests use non-today dates).
        mock_get_morning.return_value = {
            "EREGL": {"close": 42.5, "open": 42.0, "high": 43.0, "low": 41.8, "volume": 1_500_000},
            "THYAO": {"close": 285.0, "open": 280.0, "high": 290.0, "low": 278.0, "volume": 3_200_000},
        }

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

        # Use keyword arg for db_path to match new function signature.
        records = vt.prepare_morning_snapshot("2026-07-11", scored_quotes, db_path=self.db_path)
        # Should have the symbols we passed in
        symbols_found = {r["symbol"] for r in records}
        self.assertIn("EREGL", symbols_found)
        self.assertIn("THYAO", symbols_found)

    @patch("validation_tracker._get_morning_closes")
    def test_prepare_snapshot_with_close_prices(self, mock_get_morning):
        """When close_prices are provided, they should be used directly (no fetch)."""
        scored_quotes = [
            {
                "symbol": "EREGL",
                "score": 75.0,
                "raw_components": {"momentum": 12},
                "rationale": ["EMA bullish"],
            },
        ]
        close_prices = {"EREGL": 42.5}

        records = vt.prepare_morning_snapshot("2026-07-11", scored_quotes, close_prices=close_prices, db_path=self.db_path)

        # _get_morning_closes should NOT be called since close_prices were provided
        mock_get_morning.assert_not_called()
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["close_price"], 42.5)


class TestIsTradingDay(unittest.TestCase):
    """Verify weekday detection."""

    def test_weekday_is_trading_day(self):
        """Monday through Friday should return True."""
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
        records = vt.record_morning_score("2026-07-11", symbols_data, self.db_path)
        self.assertEqual(len(records), 1)


class TestLoadScoresFromFile(unittest.TestCase):
    """Test load_scores_from_file pipeline ingestion helper."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_load_list_format(self):
        """Plain list format (orchestrator scores.json) should be returned as-is."""
        scored_quotes = [
            {"symbol": "EREGL", "score": 75.0, "raw_components": {}, "rationale": []},
            {"symbol": "ASELS", "score": 35.0, "raw_components": {}, "rationale": []},
        ]
        path = os.path.join(self.tmpdir, "scores.json")
        with open(path, "w") as f:
            json.dump(scored_quotes, f)

        result = vt.load_scores_from_file(path)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["symbol"], "EREGL")
        self.assertEqual(result[1]["score"], 35.0)

    def test_load_dict_with_scores_key(self):
        """Dict format with 'scores' key (scoring_engine CLI output)."""
        data = {
            "scores": [
                {"symbol": "EREGL", "score": 75.0, "raw_components": {}, "rationale": []},
            ],
            "selection": {"top_picks": ["EREGL"]},
        }
        path = os.path.join(self.tmpdir, "scores.json")
        with open(path, "w") as f:
            json.dump(data, f)

        result = vt.load_scores_from_file(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "EREGL")

    def test_load_dict_with_top_picks_key(self):
        """Dict format with 'top_picks' key (selection.json)."""
        data = {
            "top_picks": [
                {"symbol": "THYAO", "score": 55.0, "raw_components": {}, "rationale": ["neutral"]},
            ]
        }
        path = os.path.join(self.tmpdir, "selection.json")
        with open(path, "w") as f:
            json.dump(data, f)

        result = vt.load_scores_from_file(path)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["symbol"], "THYAO")
