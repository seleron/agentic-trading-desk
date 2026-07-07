#!/usr/bin/env python3
"""Tests for admin_corrections module — override types, config loading, scoring integration."""

import json
import os
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__)))

from admin_corrections import (
    AdminCorrection,
    apply_admin_correction,
    is_ignored,
    DEFAULT_COMPONENT_WEIGHTS,
)


class TestAdminOverrideTypes(unittest.TestCase):
    """Test each override type's effect on scoring."""

    def _make_score(self, symbol="EREGL.IS", score=70, components=None):
        return {
            "symbol": symbol,
            "date": "2026-07-08",
            "score": score,
            "raw_components": components or {
                "trend": 15, "momentum": 10, "volume": 10,
                "ema_structure": 10, "pivot_position": 5, "volatility": 5,
                "technical_summary": 3, "pivot_risk": 2,
            },
            "penalties_applied": -7,
            "rationale": ["test"],
        }

    # --- force_buy ---
    def test_force_buy_raises_score_to_95(self):
        score = self._make_score("EREGL.IS", score=60)
        corr = AdminCorrection(symbol="EREGL.IS", override_type="force_buy", rationale="earnings beat")
        apply_admin_correction(score, {corr.symbol: corr}, {})
        self.assertGreaterEqual(score["score"], 95)
        self.assertEqual(score["admin_override"]["type"], "force_buy")

    def test_force_buy_preserves_higher_score(self):
        score = self._make_score("EREGL.IS", score=97)
        corr = AdminCorrection(symbol="EREGL.IS", override_type="force_buy", rationale="earnings beat")
        apply_admin_correction(score, {corr.symbol: corr}, {})
        self.assertEqual(score["score"], 97)

    # --- force_sell ---
    def test_force_sell_drops_score_to_15(self):
        score = self._make_score("EREGL.IS", score=80)
        corr = AdminCorrection(symbol="EREGL.IS", override_type="force_sell", rationale="debt downgrade")
        apply_admin_correction(score, {corr.symbol: corr}, {})
        self.assertLessEqual(score["score"], 15)
        self.assertEqual(score["admin_override"]["type"], "force_sell")

    def test_force_sell_preserves_lower_score(self):
        score = self._make_score("EREGL.IS", score=10)
        corr = AdminCorrection(symbol="EREGL.IS", override_type="force_sell", rationale="debt downgrade")
        apply_admin_correction(score, {corr.symbol: corr}, {})
        self.assertEqual(score["score"], 10)

    # --- ignore ---
    def test_ignore_sets_score_to_minus_one(self):
        score = self._make_score("EREGL.IS", score=85)
        corr = AdminCorrection(symbol="EREGL.IS", override_type="ignore", rationale="illiquid")
        apply_admin_correction(score, {corr.symbol: corr}, {})
        self.assertEqual(score["score"], -1)
        self.assertTrue(is_ignored("EREGL.IS", {"EREGL.IS": corr}))

    def test_is_not_ignored_when_no_correction(self):
        score = self._make_score("EREGL.IS", score=85)
        apply_admin_correction(score, {}, {})
        self.assertIsNone(score["admin_override"])
        self.assertFalse(is_ignored("EREGL.IS", {}))

    # --- custom_weight_modifier ---
    def test_custom_weight_modifier_adjusts_score(self):
        score = self._make_score(
            "AKBNK.IS", score=60,
            components={"trend": 15, "momentum": 10, "volume": 10,
                         "ema_structure": 10, "pivot_position": 5, "volatility": 5,
                         "technical_summary": 3, "pivot_risk": 2},
        )
        corr = AdminCorrection(
            symbol="AKBNK.IS", override_type="custom_weight_modifier",
            rationale="trend is more important", weights={"trend": 30},
        )
        apply_admin_correction(score, {corr.symbol: corr}, {})
        self.assertIsNotNone(score["admin_override"])
        self.assertEqual(score["admin_override"]["type"], "custom_weight_modifier")
        # Score should be clamped to [0,100]
        self.assertGreaterEqual(score["score"], 0)
        self.assertLessEqual(score["score"], 100)


class TestAdminConfigLoading(unittest.TestCase):
    """Test loading corrections from config dict."""

    def test_load_empty_config(self):
        with patch("admin_corrections._get_db") as mock:
            mock.return_value.execute.return_value.fetchone.return_value = None
            from admin_corrections import load_corrections_from_config
            result = load_corrections_from_config({"admin_corrections": {}})
            self.assertEqual(result, {})

    def test_load_with_override(self):
        with patch("admin_corrections._get_db") as mock:
            mock.return_value.execute.return_value.fetchone.return_value = None
            from admin_corrections import load_corrections_from_config
            config = {
                "admin_corrections": {
                    "THYAO.IS": {"type": "force_buy", "rationale": "earnings beat"},
                },
            }
            result = load_corrections_from_config(config)
            self.assertIn("THYAO.IS", result)
            self.assertEqual(result["THYAO.IS"].override_type, "force_buy")


class TestAdminCLI(unittest.TestCase):
    """Test CLI add/list/remove commands."""

    def test_cli_add(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            with patch("admin_corrections._CORRECTIONS_DB", db_path):
                import importlib
                import admin_corrections as ac
                from io import StringIO

                # Re-read schema and init
                conn = sqlite3.connect(db_path)
                for stmt in ac._SCHEMA.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        try:
                            conn.execute(stmt)
                        except Exception:
                            pass
                conn.close()

                # Test add via direct function call
                corr = ac.persist_correction("THYAO.IS", "force_buy", rationale="earnings")
                self.assertEqual(corr.symbol, "THYAO.IS")
                self.assertEqual(corr.override_type, "force_buy")

    def test_cli_list_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            with patch("admin_corrections._CORRECTIONS_DB", db_path):
                import admin_corrections as ac
                conn = sqlite3.connect(db_path)
                for stmt in ac._SCHEMA.split(";"):
                    stmt = stmt.strip()
                    if stmt:
                        try:
                            conn.execute(stmt)
                        except Exception:
                            pass
                conn.close()

                corrections = ac.list_corrections()
                self.assertEqual(corrections, [])


class TestAdminScoringIntegration(unittest.TestCase):
    """Test admin corrections integrate correctly with scoring engine."""

    def test_score_quote_with_correction(self):
        from scoring_engine import score_quote
        corr = AdminCorrection(symbol="EREGL.IS", override_type="force_buy", rationale="test")
        quote = {
            "symbol": "EREGL.IS", "close": 10.0, "open": 9.8,
            "high": 10.2, "low": 9.7, "volume": 500000,
            "rsi": 60, "macd": 0.5, "macd_signal": 0.3,
        }
        result = score_quote(quote, corr)
        self.assertGreaterEqual(result["score"], 95)
        self.assertIsNotNone(result["admin_override"])

    def test_score_quotes_passes_corrections(self):
        from scoring_engine import score_quotes
        corr = AdminCorrection(symbol="EREGL.IS", override_type="force_buy", rationale="test")
        corrections = {"EREGL.IS": corr}
        quotes = [
            {"symbol": "EREGL.IS", "close": 10.0, "open": 9.8, "high": 10.2, "low": 9.7,
             "volume": 500000, "rsi": 60, "macd": 0.5, "macd_signal": 0.3},
            {"symbol": "TUPRS.IS", "close": 20.0, "open": 19.8, "high": 20.5, "low": 19.5,
             "volume": 400000, "rsi": 70, "macd": -0.2, "macd_signal": 0.1},
        ]
        results = score_quotes(quotes, corrections)
        self.assertEqual(len(results), 2)
        # First quote should have force_buy applied
        self.assertGreaterEqual(results[0]["score"], 95)
        self.assertIsNotNone(results[0].get("admin_override"))
        # Second quote should not have correction
        self.assertIsNone(results[1].get("admin_override"))


if __name__ == "__main__":
    unittest.main()
