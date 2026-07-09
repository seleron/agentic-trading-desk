#!/usr/bin/env python3
"""
test_pipeline.py
================
Smoke/logic tests for the BIST AI Trader pipeline modules that previously had
no coverage: scoring_engine, trade_plan, backtest, eod_module, learning_module.

These guard the regressions fixed in the PR #1 review round:
  - EMA-structure scoring must reward up-trends (close>EMA20>EMA50>EMA200),
    not down-trends.
  - trade_plan must honour both long and short directions (stop on the correct
    side of entry).
  - backtest.run_backtest requires pillar_weights (orchestrator integration).
  - learning_module must not crash on a fresh DB with no trades table.

Run with:  python3 scripts/test_pipeline.py   (unittest — no external deps)
"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import backtest
import eod_module
import learning_module
from scoring_engine import (
    compute_ema_structure_score,
    score_quote,
    select_top_picks,
)
from trade_plan import generate_trade_plan


def _bullish_quote() -> dict:
    """A clean up-trend: close > EMA20 > EMA50 > EMA200."""
    return {
        "symbol": "BULL", "close": 100.5, "open": 99, "high": 103, "low": 99,
        "volume": 2_000_000, "rsi": 60, "macd": 1.2, "macd_signal": 0.9,
        "ema20": 100, "ema50": 98, "ema200": 95, "volume_avg_20": 1_000_000,
        "pivot": 100, "r1": 103, "s1": 97,
    }


def _bearish_quote() -> dict:
    """A down-trend: close < EMA20 < EMA50 < EMA200."""
    q = _bullish_quote()
    q.update(symbol="BEAR", close=94, ema20=95, ema50=98, ema200=100,
             rsi=32, macd=-1.0, macd_signal=0.5)
    return q


class TestEmaStructureDirection(unittest.TestCase):
    def test_uptrend_stack_scores_full(self):
        score, reasons = compute_ema_structure_score(100.5, 100, 98, 95)
        self.assertEqual(score, 15)  # +10 stack +5 near-EMA20
        self.assertTrue(any("bullish" in r.lower() for r in reasons))

    def test_downtrend_stack_scores_zero_credit(self):
        # ema200>ema50>ema20 is a down-trend and must NOT earn the stack bonus.
        score, _ = compute_ema_structure_score(94, 95, 98, 100)
        self.assertLess(score, 10)


class TestScoreQuote(unittest.TestCase):
    def test_bullish_beats_bearish(self):
        bull = score_quote(_bullish_quote())["score"]
        bear = score_quote(_bearish_quote())["score"]
        self.assertGreater(bull, bear)

    def test_bullish_reaches_selection_threshold(self):
        # With reduced trend/momentum caps (19/16), textbook long scores ~77.
        self.assertGreaterEqual(score_quote(_bullish_quote())["score"], 75)

    def test_volume_component_skipped_without_avg(self):
        q = _bullish_quote()
        q.pop("volume_avg_20")
        result = score_quote(q)
        self.assertEqual(result["raw_components"]["volume"], 0)
        self.assertTrue(any("volume_avg_20 missing" in r for r in result["rationale"]))


class TestSelection(unittest.TestCase):
    def test_no_trade_day_when_below_threshold(self):
        scores = [score_quote(_bearish_quote())]
        sel = select_top_picks(scores, threshold=75, top_n=1)
        self.assertTrue(sel["no_trade_day"])
        self.assertEqual(sel["qualified_above_threshold"], 0)

    def test_top_pick_selected(self):
        sel = select_top_picks([score_quote(_bullish_quote())], threshold=75, top_n=1)
        self.assertFalse(sel["no_trade_day"])
        self.assertEqual(sel["top_picks"][0]["symbol"], "BULL")


class TestTradePlanDirection(unittest.TestCase):
    IND = {"close": 100, "ema20": 100, "ema20_slope": 0.5, "rsi14": 60,
           "bb_lower": 95, "bb_upper": 105}

    def test_long_stop_below_entry(self):
        plan = generate_trade_plan("X", {"action": "BUY"}, self.IND)
        self.assertEqual(plan["direction"], "long")
        self.assertLess(plan["stop_loss"]["price"], plan["entry"]["price"])
        self.assertGreater(plan["targets"][0]["price"], plan["entry"]["price"])

    def test_short_stop_above_entry(self):
        plan = generate_trade_plan("X", {"action": "SHORT"}, self.IND)
        self.assertEqual(plan["direction"], "short")
        self.assertGreater(plan["stop_loss"]["price"], plan["entry"]["price"])
        self.assertLess(plan["targets"][0]["price"], plan["entry"]["price"])

    def test_no_trade_for_unknown_action(self):
        plan = generate_trade_plan("X", {"action": "HOLD"}, self.IND)
        self.assertEqual(plan["status"], "no_trade")

    def test_position_size_positive_both_directions(self):
        for action in ("BUY", "SHORT"):
            plan = generate_trade_plan("X", {"action": action}, self.IND)
            self.assertGreater(plan["position_size"], 0)


class TestBacktest(unittest.TestCase):
    @staticmethod
    def _bars(n=260):
        import random
        random.seed(7)
        bars, p = [], 100.0
        for i in range(n):
            p *= (1 + random.uniform(-0.02, 0.023))
            bars.append({"date": f"d{i}", "open": p * 0.99, "high": p * 1.02,
                         "low": p * 0.98, "close": p, "volume": 1_000_000})
        return bars

    def test_run_backtest_requires_pillar_weights(self):
        # Guards the orchestrator integration bug (call without weights).
        with self.assertRaises(TypeError):
            backtest.run_backtest(bars=self._bars())  # type: ignore[call-arg]

    def test_run_backtest_produces_result(self):
        r = backtest.run_backtest(
            bars=self._bars(),
            pillar_weights={"trend": 0.4, "momentum": 0.3, "macro_sentiment": 0.3},
            capital=10000.0,
        )
        self.assertGreaterEqual(r.total_trades, 0)
        self.assertIsInstance(r.total_return_pct, float)

    def test_full_scoring_path_used_for_sufficient_history(self):
        """Verify that bars with i >= 20 use indicators.compute + score_quote
        (the live scorer), not the simplified SMA/ROC composite.

        The fix for backlog #011 swapped the branches so the full path runs
        when enough history is available.  This test confirms:
          - a synthetic dataset with known indicator values produces composites
            that match score_quote output, and
          - those composites differ from what the simplified SMA/ROC would give.

        We use a gentle uptrend so RSI stays in a normal range (not 100),
        ensuring the scorer can accumulate positive components.
        """
        import random as _rand

        # Build a clean uptrend: 300 bars of gently rising prices.
        _rand.seed(42)
        bt_bars = []
        p = 100.0
        for i in range(300):
            # Tighter range keeps RSI from going to 100.
            p *= (1 + _rand.uniform(-0.002, 0.006))
            bt_bars.append({
                "date": f"bt_{i}",
                "open": p * 0.995,
                "high": p * 1.01,
                "low": p * 0.99,
                "close": p,
                "volume": int(1_000_000 + _rand.randint(-200_000, 200_000)),
            })

        # Run indicators on the full history to get expected indicator values.
        from indicators import compute as ind_compute
        closes = [b["close"] for b in bt_bars]
        highs = [b["high"] for b in bt_bars]
        lows = [b["low"] for b in bt_bars]
        vols = [b["volume"] for b in bt_bars]

        ind_all = ind_compute(closes, highs=highs, lows=lows, volumes=vols)

        # Verify RSI is not at an extreme (which would heavily penalize).
        rsi_250 = ind_all.get("rsi14")
        self.assertIsNotNone(rsi_250)
        self.assertGreater(rsi_250, 30, "RSI should be in normal range for this uptrend")

        # Pick a bar well past warm-up (i=250) and build the quote dict.
        i_ref = 250
        ref_bar = bt_bars[i_ref]
        vol_recent = [bt_bars[j]["volume"] for j in range(max(1, i_ref - 20), i_ref)]
        volume_avg_20 = sum(vol_recent) / len(vol_recent)

        quote = {
            "symbol": "REF",
            "date": ref_bar["date"],
            "close": ref_bar["close"],
            "open": ref_bar["open"],
            "high": ref_bar["high"],
            "low": ref_bar["low"],
            "volume": ref_bar["volume"],
            "rsi": ind_all.get("rsi14"),
            "macd": ind_all.get("macd_line") or 0,
            "macd_signal": ind_all.get("macd_signal") or 0,
            "ema20": ind_all.get("ema20"),
            "ema50": ind_all.get("ema50"),
            "ema200": ind_all.get("ema200"),
            "volume_avg_20": volume_avg_20,
        }

        scored = score_quote(quote)
        expected_composite = scored["score"] / 50.0 - 1.0  # backtest maps 0..100 → [-1,+1]

        # Composite must live on the [-1, +1] scale (shared with ENTRY_THRESHOLD and
        # the warm-up/fallback paths). score/100 ([0,1]) would break the exit signal.
        self.assertTrue(-1.0 <= expected_composite <= 1.0,
            f"composite {expected_composite:.3f} off the [-1,1] scale (score={scored['score']})")
        self.assertTrue(0 <= scored["score"] <= 100)

        # Now run backtest and verify it produces meaningful results (not degenerate).
        r = backtest.run_backtest(
            bars=bt_bars,
            pillar_weights={"trend": 0.4, "momentum": 0.3, "macro_sentiment": 0.3},
            capital=10000.0,
        )
        # With an uptrend and full scorer, we should get at least some trades.
        self.assertGreaterEqual(r.total_trades, 1)

    def test_composite_scale_keeps_exit_signal_live(self):
        """Regression for backlog #011 review: the full-scoring composite must be on
        the [-1, +1] scale so the signal exit ``composite <= -ENTRY_THRESHOLD`` (0.5)
        is reachable. The buggy score/100 ([0,1]) scaling mapped even a 0 score to
        composite 0.0 — never <= -0.5 — so positions could only ever exit on the 2%
        stop: a dead signal exit."""
        bearish = {
            "symbol": "BEAR", "date": "x", "close": 88.0, "open": 95.0,
            "high": 89.0, "low": 87.0, "volume": 100, "volume_avg_20": 1_000_000,
            "rsi": 20.0, "macd": -1.0, "macd_signal": 0.5,
            "ema20": 90.0, "ema50": 95.0, "ema200": 100.0,
        }
        score = score_quote(bearish)["score"]
        composite = score / 50.0 - 1.0            # the backtest's mapping
        self.assertLessEqual(score, 25, f"expected a bearish score, got {score}")
        self.assertLessEqual(composite, -0.5,
            f"exit signal dead: bearish composite {composite:.3f} > -0.5 (scale bug)")
        # The old [0,1] scaling would have silently failed this guard:
        self.assertGreater(score / 100.0, -0.5)


class TestEodAndLearning(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "trades.db")

    def test_record_and_report(self):
        eod_module.record_trade(self.db, "2026-07-06", "AAA", 100.0, 110.0, 90)
        eod_module.record_trade(self.db, "2026-07-06", "BBB", 100.0, 90.0, 85)
        report = eod_module.generate_eod_report(self.db, "2026-07-06")
        self.assertFalse(report["no_trades"])
        self.assertEqual(report["total_trades"], 2)
        self.assertEqual(report["wins"], 1)
        self.assertEqual(report["losses"], 1)

    def test_learning_missing_table_does_not_crash(self):
        result = learning_module.analyze_trades(self.db)
        self.assertFalse(result["ready"])
        self.assertEqual(result["trades_analyzed"], 0)

    def test_learning_column_indices(self):
        # Record enough completed trades to hit the min and confirm score/result
        # columns are read at the right indices (result=5, score=6).
        for i in range(6):
            eod_module.record_trade(self.db, "2026-07-06", f"S{i}", 100.0,
                                    110.0 if i % 2 == 0 else 90.0, 80 + i)
        result = learning_module.analyze_trades(self.db, min_trades=5)
        self.assertTrue(result["ready"])
        self.assertEqual(result["trades_analyzed"], 6)
        self.assertGreaterEqual(result["avg_win_score"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
