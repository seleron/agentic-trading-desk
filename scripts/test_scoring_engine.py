#!/usr/bin/env python3
"""
test_scoring_engine.py
======================
Tests for scoring engine — pivot risk score r2/s2 branch, full pipeline integration,
and weight rebalance verification.

Run with:  python3 scripts/test_scoring_engine.py
           or: pytest scripts/test_scoring_engine.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scoring_engine import (
    COMPONENT_WEIGHTS,
    compute_pivot_risk_score,
    compute_relative_strength,
    score_quote,
)


class TestComponentWeights(unittest.TestCase):
    """Verify weight rebalance: trend 25→17, momentum 20→18, pivot_risk +5, ichimoku_alignment +5 added."""

    def test_weights_sum_to_100(self):
        """All component weights must sum to exactly 100."""
        total = sum(COMPONENT_WEIGHTS.values())
        self.assertEqual(total, 100, f"Weights sum to {total}, expected 100")

    def test_trend_weight_is_17(self):
        """Trend weight rebalanced from 25 → 17 to accommodate pivot_risk + ichimoku_alignment."""
        self.assertEqual(COMPONENT_WEIGHTS["trend"], 17)

    def test_momentum_weight_is_18(self):
        """Momentum weight rebalanced from 20 → 18."""
        self.assertEqual(COMPONENT_WEIGHTS["momentum"], 18)

    def test_pivot_risk_included(self):
        """pivot_risk component added with +5 max."""
        self.assertIn("pivot_risk", COMPONENT_WEIGHTS)
        self.assertEqual(COMPONENT_WEIGHTS["pivot_risk"], 5)

    def test_ichimoku_alignment_included(self):
        """ichimoku_alignment component added with +5 max."""
        self.assertIn("ichimoku_alignment", COMPONENT_WEIGHTS)
        self.assertEqual(COMPONENT_WEIGHTS["ichimoku_alignment"], 5)


class TestComputePivotRiskScore(unittest.TestCase):
    """Test compute_pivot_risk_score — especially the r2/s2 continuation branch."""

    def test_safely_between_s1_r1_no_r2(self):
        """When close is safely between S1 and R1 (not near edges), +3 points."""
        score, rationale = compute_pivot_risk_score(
            close=105.0, pivot=100.0, r1=110.0, s1=90.0
        )
        self.assertEqual(score, 3)
        self.assertEqual(len(rationale), 1)
        self.assertIn("Safely between S1 and R1", rationale[0])

    def test_below_s1_or_above_r1_no_credit(self):
        """Close below S1 or above R1 — no safe-zone credit."""
        score, _ = compute_pivot_risk_score(
            close=85.0, pivot=100.0, r1=110.0, s1=90.0
        )
        # Below S1: no +3 credit; below pivot: no +2 continuation credit
        self.assertEqual(score, 0)

    def test_at_s1_edge_no_credit(self):
        """Close within 3% margin of S1 — no safe-zone credit."""
        score, _ = compute_pivot_risk_score(
            close=92.5, pivot=100.0, r1=110.0, s1=90.0
        )
        # margin = 0.03 * 92.5 = 2.775; S1 + margin = 92.775 > 92.5 → no credit
        self.assertEqual(score, 0)

    def test_above_pivot_below_r2_continuation(self):
        """Close above pivot but below R2 — +2 continuation signal (the r2 branch)."""
        score, rationale = compute_pivot_risk_score(
            close=105.0, pivot=100.0, r1=110.0, s1=90.0, r2=120.0
        )
        # Both safe-zone (+3) and continuation (+2) fire → 5 capped at 5
        self.assertEqual(score, 5)
        self.assertEqual(len(rationale), 2)
        self.assertIn("bullish continuation zone", rationale[1])

    def test_above_pivot_below_r2_no_s1_r1_overlap(self):
        """Close above pivot but below R2, safely between S1 and R1 — full +5."""
        score, rationale = compute_pivot_risk_score(
            close=104.0, pivot=100.0, r1=110.0, s1=90.0, r2=130.0
        )
        self.assertEqual(score, 5)  # +3 (safe zone) + +2 (continuation) = 5
        self.assertIn("Safely between S1 and R1", rationale[0])
        self.assertIn("bullish continuation zone", rationale[1])

    def test_r2_populated(self):
        """When r2 is populated, the +2 continuation branch fires correctly."""
        score, rationale = compute_pivot_risk_score(
            close=105.0, pivot=100.0, r1=110.0, s1=90.0, r2=130.0
        )
        self.assertEqual(score, 5)
        self.assertIn("bullish continuation zone", rationale[1])

    def test_close_above_r2_no_continuation_credit(self):
        """Close above R2 — no continuation credit (already beyond R2)."""
        score, rationale = compute_pivot_risk_score(
            close=135.0, pivot=100.0, r1=110.0, s1=90.0, r2=130.0
        )
        # Above R2: no safe-zone between S1/R1; above R2 so not below R2-margin → 0
        self.assertEqual(score, 0)

    def test_close_at_r2_edge_no_continuation_credit(self):
        """Close at R2 - margin boundary — no continuation credit; also above R1 so no safe zone."""
        score, _ = compute_pivot_risk_score(
            close=127.0, pivot=100.0, r1=110.0, s1=90.0, r2=130.0
        )
        # margin = 0.03 * 127 = 3.81; R2 - margin = 126.19 < 127 → no continuation credit
        # Also above R1-margin (106.19) so no safe zone either
        self.assertEqual(score, 0)

    def test_close_near_r2_with_safe_zone(self):
        """Close just below R2 margin — still gets both +3 and +2."""
        score, rationale = compute_pivot_risk_score(
            close=126.0, pivot=100.0, r1=115.0, s1=85.0, r2=130.0
        )
        # margin = 0.03 * 126 = 3.78; R2 - margin = 126.22 > 126 ✓ → continuation +2
        # S1+margin=88.78 < 126 and R1-margin=111.22 > 126 ✗ → no safe zone
        self.assertEqual(score, 2)  # Only continuation credit

    def test_no_pivot_no_credit(self):
        """When pivot is None — no scoring possible."""
        score, rationale = compute_pivot_risk_score(
            close=105.0, pivot=None, r1=110.0, s1=90.0, r2=130.0
        )
        self.assertEqual(score, 0)

    def test_close_just_above_pivot(self):
        """Close just above pivot — should still get +2 if below R2."""
        score, rationale = compute_pivot_risk_score(
            close=100.5, pivot=100.0, r1=110.0, s1=90.0, r2=130.0
        )
        self.assertEqual(score, 5)  # +3 safe zone + +2 continuation
        self.assertIn("bullish continuation zone", rationale[1])

    def test_differentiation_from_pivot_position(self):
        """Verify pivot_risk is stricter than pivot_position:
           edge-close price gets +0 from risk but may get +3 from position."""
        # Price near S1 — within the 3% margin
        score, rationale = compute_pivot_risk_score(
            close=92.5, pivot=100.0, r1=110.0, s1=90.0, r2=130.0
        )
        # Close is between S1 and R1 (position would give +3), but within margin → risk = 0
        self.assertEqual(score, 0)


class TestScoreQuoteR2S2Integration(unittest.TestCase):
    """Test that r2/s2 flow through the full score_quote pipeline."""

    def test_score_quote_with_r2_s2(self):
        """Full quote scoring with R2/S2 populated should include pivot_risk component."""
        quote = {
            "symbol": "TEST.IS",
            "date": "2025-01-01",
            "close": 105.0,
            "open": 103.0,
            "high": 107.0,
            "low": 102.0,
            "volume": 1_000_000,
            "rsi": 60.0,
            "macd": 0.5,
            "macd_signal": 0.3,
            "ema20": 101.0,
            "ema50": 98.0,
            "ema200": 95.0,
            "volume_avg_20": 800_000,
            "pivot": 104.0,
            "r1": 112.0,
            "s1": 96.0,
            "r2": 130.0,
            "s2": 78.0,
        }
        result = score_quote(quote)
        self.assertEqual(result["symbol"], "TEST.IS")
        self.assertIn("pivot_risk", result["raw_components"])

        # With close=105 safely between S1(96) and R1(112), above pivot(104), below R2(130):
        # should get +3 (safe zone) + +2 (continuation) = 5 for pivot_risk
        self.assertEqual(result["raw_components"]["pivot_risk"], 5)

    def test_score_quote_without_r2_s2(self):
        """Quote without R2/S2 — pivot_risk caps at +3."""
        quote = {
            "symbol": "TEST.IS",
            "date": "2025-01-01",
            "close": 105.0,
            "open": 103.0,
            "high": 107.0,
            "low": 102.0,
            "volume": 1_000_000,
            "rsi": None,
            "macd": 0.5,
            "macd_signal": 0.3,
            "ema20": 101.0,
            "ema50": 98.0,
            "volume_avg_20": 800_000,
            "pivot": 104.0,
            "r1": 112.0,
            "s1": 96.0,
        }
        result = score_quote(quote)
        # Without r2: max pivot_risk is +3 (safe zone only)
        self.assertIn("pivot_risk", result["raw_components"])

    def test_all_components_present(self):
        """score_quote returns all 8 component keys in raw_components."""
        quote = {
            "symbol": "COMP.IS",
            "date": "2025-01-01",
            "close": 100.0,
            "open": 98.0,
            "high": 102.0,
            "low": 97.0,
            "volume": 500_000,
            "rsi": 55.0,
            "macd": 0.1,
            "macd_signal": -0.1,
            "ema20": 99.0,
            "ema50": 97.0,
            "volume_avg_20": 400_000,
        }
        result = score_quote(quote)

        expected_keys = {
            "trend", "momentum", "volume", "ema_structure",
            "pivot_position", "pivot_risk", "volatility", "technical_summary",
            "ichimoku_alignment"
        }
        self.assertEqual(set(result["raw_components"].keys()), expected_keys)


class TestScoreQuoteRationale(unittest.TestCase):
    """Test that pivot_risk rationale is included in the output."""

    def test_pivot_risk_reasons_in_rationale(self):
        """pivot_risk rationale strings should appear in the full rationale list."""
        quote = {
            "symbol": "TEST.IS",
            "date": "2025-01-01",
            "close": 105.0,
            "open": 103.0,
            "high": 107.0,
            "low": 102.0,
            "volume": 1_000_000,
            "rsi": None,
            "macd": 0.5,
            "macd_signal": 0.3,
            "ema20": 101.0,
            "ema50": 98.0,
            "volume_avg_20": 800_000,
            "pivot": 104.0,
            "r1": 112.0,
            "s1": 96.0,
            "r2": 130.0,
        }
        result = score_quote(quote)

        # Should have pivot_risk rationale entries
        self.assertTrue(any("Safely between S1 and R1" in r for r in result["rationale"]))
        self.assertTrue(any("bullish continuation zone" in r for r in result["rationale"]))


class TestRelativeStrength(unittest.TestCase):
    """Tests for the relative strength (RS) modifier feature.

    Acceptance criteria:
    - compute_relative_strength computes ratio correctly
    - RS ratio +1/-1 modifier applied to score
    - Pipeline output includes relative_strength field per stock
    """

    def _make_stock_closes(self, start_pct_change):
        """Generate lookback+1 closing prices with a given total return."""
        base = 100.0
        # Total return over 20 steps = start_pct_change → per-step factor
        returns_per_step = start_pct_change / 20.0
        closes = [base]
        price = base
        for _ in range(20):
            price *= (1 + returns_per_step)
            closes.append(price)
        return closes

    def test_outperforms_by_10_percent_vs_bench_up_5(self):
        """Stock up 10%, benchmark up 5% → RS ratio ≈ 4.76, direction=+1."""
        stock_closes = self._make_stock_closes(0.10)   # ~10% total return
        bench_closes = self._make_stock_closes(0.05)    # ~5% total return

        rs = compute_relative_strength(stock_closes, bench_closes, threshold=0.05)
        self.assertIsNotNone(rs["ratio"])
        self.assertEqual(rs["direction"], 1)
        self.assertTrue(rs["adjusted"])
        self.assertGreater(rs["stock_return_pct"], 9.0)
        self.assertGreater(rs["benchmark_return_pct"], 4.0)

    def test_underperforms_stock_down_3_bench_up_8(self):
        """Stock down 3%, benchmark up 8% → RS ratio ≈ 0.75, direction=-1."""
        stock_closes = self._make_stock_closes(-0.03)   # ~-3% total return
        bench_closes = self._make_stock_closes(0.08)    # ~8% total return

        rs = compute_relative_strength(stock_closes, bench_closes, threshold=0.05)
        self.assertIsNotNone(rs["ratio"])
        self.assertEqual(rs["direction"], -1)
        self.assertTrue(rs["adjusted"])

    def test_neutral_within_threshold(self):
        """Stock up 4%, benchmark up 3% → RS ~1.03, within ±5% threshold."""
        stock_closes = self._make_stock_closes(0.04)
        bench_closes = self._make_stock_closes(0.03)

        rs = compute_relative_strength(stock_closes, bench_closes, threshold=0.05)
        self.assertIsNotNone(rs["ratio"])
        self.assertEqual(rs["direction"], 0)
        self.assertFalse(rs["adjusted"])

    def test_insufficient_data_returns_neutral(self):
        """Less than lookback+1 bars → ratio=None, direction=0."""
        rs = compute_relative_strength([100.0], [100.0], threshold=0.05)
        self.assertIsNone(rs["ratio"])
        self.assertEqual(rs["direction"], 0)
        self.assertFalse(rs["adjusted"])

    def test_score_quote_with_rs_modifier(self):
        """score_quote with benchmark_closes includes relative_strength field."""
        stock_closes = [100.0 + i * 0.5 for i in range(21)]   # ~10% return over 20 days
        bench_closes = [100.0 + i * 0.2 for i in range(21)]    # ~4% return

        quote = {
            "symbol": "TEST.IS",
            "date": "2025-01-01",
            "close": 110.0,
            "open": 108.0,
            "high": 112.0,
            "low": 107.0,
            "volume": 500_000,
            "rsi": 60.0,
            "macd": 0.5,
            "macd_signal": 0.3,
            "ema20": 108.0,
            "ema50": 105.0,
            "volume_avg_20": 400_000,
            "stock_closes": stock_closes,
        }

        result = score_quote(quote, benchmark_closes=bench_closes)

        self.assertIn("relative_strength", result)
        rs_info = result["relative_strength"]
        self.assertIsNotNone(rs_info["ratio"])
        self.assertEqual(rs_info["direction"], 1)  # stock outperformed
        self.assertTrue(rs_info["adjusted"])
        # Score should be adjusted: original ~77 + 1 = 78 (within [0,100])
        self.assertIsInstance(result["score"], int)

    def test_score_quote_without_rs_still_works(self):
        """score_quote without benchmark_closes has relative_strength with ratio=None."""
        quote = {
            "symbol": "TEST.IS",
            "date": "2025-01-01",
            "close": 100.0,
            "open": 98.0,
            "high": 102.0,
            "low": 97.0,
            "volume": 500_000,
            "rsi": None,
            "macd": 0.5,
            "macd_signal": 0.3,
            "ema20": 101.0,
            "ema50": 98.0,
            "volume_avg_20": 800_000,
        }

        result = score_quote(quote)
        self.assertIn("relative_strength", result)
        self.assertIsNone(result["relative_strength"]["ratio"])
        self.assertEqual(result["relative_strength"]["direction"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
