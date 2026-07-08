#!/usr/bin/env python3
"""
test_scoring_invariants.py
==========================
Property/invariant tests for the scoring engine that guard whole *classes* of bug,
not just single cases:

  * Every component function must return a score in [0, COMPONENT_WEIGHTS[name]].
    A regression here is exactly the cap≠weight drift that let `trend` return 19
    (weight 17) and `momentum` cap at 16 (weight 18), skewing every final score and
    breaking the custom_weight_modifier normalization.
  * score_quote must always return a score in [0, 100] with every raw component
    within its weight, for a wide variety of quotes (bullish/bearish/None-laden/
    extreme), i.e. no input should be able to violate the invariant.
  * select_top_picks market_bias must be computed from genuine model scores only —
    admin-override sentinel scores (ignore→-1, force_buy→95, force_sell→15) must not
    pollute the average.

Run:  python3 -m unittest scripts.test_scoring_invariants
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scoring_engine import (  # noqa: E402
    COMPONENT_WEIGHTS,
    compute_trend_score,
    compute_momentum_score,
    compute_volume_score,
    compute_ema_structure_score,
    compute_pivot_score,
    compute_pivot_risk_score,
    compute_volatility_score,
    compute_technical_summary_score,
    compute_ichimoku_alignment_score,
    score_quote,
    select_top_picks,
)


def _component_scores(q: dict) -> dict[str, int]:
    """Run every component function against a quote-like dict and collect scores."""
    ich = q.get("_ichimoku")
    return {
        "trend": compute_trend_score(q["close"], q.get("ema20"), q.get("ema50"), q.get("ema200"))[0],
        "momentum": compute_momentum_score(q.get("rsi"), q.get("macd", 0), q.get("macd_signal", 0), q["close"], q.get("ema20"))[0],
        "volume": compute_volume_score(q.get("volume", 0), q.get("volume_avg_20", 0) or 0)[0],
        "ema_structure": compute_ema_structure_score(q["close"], q.get("ema20"), q.get("ema50"), q.get("ema200"))[0],
        "pivot_position": compute_pivot_score(q["close"], q.get("pivot"), q.get("r1"), q.get("s1"))[0],
        "pivot_risk": compute_pivot_risk_score(q["close"], q.get("pivot"), q.get("r1"), q.get("s1"), q.get("r2"))[0],
        "volatility": compute_volatility_score(q.get("high", q["close"]), q.get("low", q["close"]), q["close"])[0],
        "technical_summary": compute_technical_summary_score(q["close"], q.get("open", q["close"]), q.get("high", q["close"]), q.get("low", q["close"]))[0],
        "ichimoku_alignment": compute_ichimoku_alignment_score(q["close"], ich)[0],
    }


def _sample_quotes() -> list[dict]:
    """A spread of quotes designed to stress every component and edge."""
    ich_bull = {"tenkan_sen": 110.0, "kijun_sen": 100.0, "senkou_span_a": 102.0, "senkou_span_b": 101.0, "chikou_span": 100.0}
    return [
        # Maxed-out bull: everything that can fire, fires.
        {"symbol": "MAX", "close": 105.0, "open": 104.6, "high": 108.0, "low": 104.5,
         "volume": 10_000_000, "volume_avg_20": 1_000_000, "rsi": 60.0, "macd": 1.0, "macd_signal": 0.0,
         "ema20": 104.0, "ema50": 100.0, "ema200": 95.0, "pivot": 104.0, "r1": 112.0, "s1": 96.0, "r2": 130.0,
         "_ichimoku": ich_bull},
        # Deep bear.
        {"symbol": "BEAR", "close": 90.0, "open": 95.0, "high": 96.0, "low": 89.0,
         "volume": 100, "volume_avg_20": 1_000_000, "rsi": 25.0, "macd": -1.0, "macd_signal": 0.0,
         "ema20": 95.0, "ema50": 100.0, "ema200": 110.0, "pivot": 100.0, "r1": 110.0, "s1": 92.0},
        # Overbought (penalty path) + huge volume.
        {"symbol": "OB", "close": 200.0, "high": 210.0, "low": 199.0, "open": 199.5,
         "volume": 50_000_000, "volume_avg_20": 1_000_000, "rsi": 92.0, "macd": 2.0, "macd_signal": 1.0,
         "ema20": 190.0, "ema50": 180.0, "ema200": 170.0},
        # Sparse: only close; all optionals absent/None.
        {"symbol": "SPARSE", "close": 50.0, "rsi": None},
        # Zero/degenerate volume + None indicators.
        {"symbol": "ZEROV", "close": 10.0, "high": 10.0, "low": 10.0, "open": 10.0,
         "volume": 0, "volume_avg_20": 0, "rsi": None, "ema20": None, "ema50": None, "ema200": None},
        # Extreme oversold.
        {"symbol": "OS", "close": 5.0, "high": 6.0, "low": 4.0, "open": 5.5,
         "volume": 1, "volume_avg_20": 100, "rsi": 3.0, "macd": -0.5, "macd_signal": 0.1,
         "ema20": 6.0, "ema50": 7.0, "ema200": 8.0},
    ]


class TestComponentCapInvariant(unittest.TestCase):
    def test_every_component_within_its_weight(self):
        """No component may ever return more than its declared COMPONENT_WEIGHTS value
        (nor a negative score) for ANY of the sample quotes."""
        for q in _sample_quotes():
            for comp, val in _component_scores(q).items():
                self.assertGreaterEqual(val, 0, f"{q['symbol']}: {comp} negative ({val})")
                self.assertLessEqual(
                    val, COMPONENT_WEIGHTS[comp],
                    f"{q['symbol']}: {comp}={val} exceeds weight {COMPONENT_WEIGHTS[comp]}",
                )

    def test_trend_cap_binds_at_weight(self):
        """Trend raw can reach 35 (15+10+10); it must cap at the weight, not 19."""
        score, _ = compute_trend_score(close=105.0, ema20=104.0, ema50=100.0, ema200=95.0)
        self.assertEqual(score, COMPONENT_WEIGHTS["trend"])
        self.assertEqual(score, 17)

    def test_momentum_cap_binds_at_weight(self):
        """Momentum raw can reach 25 (15+10); it must cap at the weight (18), not 16."""
        score, _ = compute_momentum_score(rsi=70.0, macd=1.0, macd_signal=0.0, close=100.0, ema20=95.0)
        self.assertEqual(score, COMPONENT_WEIGHTS["momentum"])
        self.assertEqual(score, 18)


class TestScoreQuoteInvariants(unittest.TestCase):
    def test_score_in_range_and_components_capped(self):
        for q in _sample_quotes():
            r = score_quote(q)
            self.assertTrue(0 <= r["score"] <= 100, f"{q['symbol']}: score {r['score']} out of [0,100]")
            for comp, val in r["raw_components"].items():
                self.assertLessEqual(val, COMPONENT_WEIGHTS[comp], f"{q['symbol']}: {comp} over weight")
                self.assertGreaterEqual(val, 0)

    def test_raw_total_cannot_exceed_100(self):
        """Sum of all component weights is exactly 100, so raw_total can never exceed it."""
        self.assertEqual(sum(COMPONENT_WEIGHTS.values()), 100)
        for q in _sample_quotes():
            comps = score_quote(q)["raw_components"]
            self.assertLessEqual(sum(comps.values()), 100)


class TestSelectTopPicksBias(unittest.TestCase):
    @staticmethod
    def _scored(symbol, score, override=None):
        return {"symbol": symbol, "score": score, "rationale": [], "raw_components": {},
                "admin_override": override}

    def test_admin_overrides_excluded_from_market_bias(self):
        genuine = [self._scored(f"S{i}", 60) for i in range(5)]
        ignored = [self._scored(f"I{i}", -1, {"type": "ignore"}) for i in range(3)]
        sel = select_top_picks(genuine + ignored, threshold=80, top_n=2)
        # Without the fix, avg would be (5*60 + 3*-1)/8 = 37.1 → "negative".
        self.assertEqual(sel["avg_score_all_stocks"], 60.0)
        self.assertEqual(sel["market_bias"], "positive")
        self.assertEqual(sel["total_scanned"], 8)  # count still reflects everything scanned

    def test_force_buy_does_not_inflate_bias(self):
        genuine = [self._scored(f"S{i}", 40) for i in range(4)]
        forced = [self._scored("FB", 95, {"type": "force_buy"})]
        sel = select_top_picks(genuine + forced, threshold=80, top_n=2)
        self.assertEqual(sel["avg_score_all_stocks"], 40.0)
        self.assertEqual(sel["market_bias"], "negative")

    def test_all_overridden_no_zero_division(self):
        only = [self._scored("X", 95, {"type": "force_buy"})]
        sel = select_top_picks(only)  # must not raise ZeroDivisionError
        self.assertEqual(sel["avg_score_all_stocks"], 0)
        self.assertIn("market_bias", sel)


if __name__ == "__main__":
    unittest.main(verbosity=2)
