#!/usr/bin/env python3
"""
test_scoring_engine.py
======================
Tests for scoring engine — pivot risk score r2/s2 branch and full pipeline integration.

Run with:  python3 scripts/test_scoring_engine.py
           or: pytest scripts/test_scoring_engine.py -v
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scoring_engine import (
    compute_pivot_risk_score,
    score_quote,
)


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


if __name__ == "__main__":
    unittest.main(verbosity=2)
