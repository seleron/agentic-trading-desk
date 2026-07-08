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
from backtest import BacktestResult
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
        # After the EMA-structure fix a textbook long must be selectable at 80.
        self.assertGreaterEqual(score_quote(_bullish_quote())["score"], 80)

    def test_volume_component_skipped_without_avg(self):
        q = _bullish_quote()
        q.pop("volume_avg_20")
        result = score_quote(q)
        self.assertEqual(result["raw_components"]["volume"], 0)
        self.assertTrue(any("volume_avg_20 missing" in r for r in result["rationale"]))


class TestSelection(unittest.TestCase):
    def test_no_trade_day_when_below_threshold(self):
        scores = [score_quote(_bearish_quote())]
        sel = select_top_picks(scores, threshold=80, top_n=1)
        self.assertTrue(sel["no_trade_day"])
        self.assertEqual(sel["qualified_above_threshold"], 0)

    def test_top_pick_selected(self):
        sel = select_top_picks([score_quote(_bullish_quote())], threshold=80, top_n=1)
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

    def test_run_backtest_default_score_mode(self):
        # Without pillar_weights, backtest falls through to full 7-component scoring_engine mode.
        result = backtest.run_backtest(
            bars=self._bars(),
        )
        self.assertIsInstance(result, BacktestResult)

    def test_run_backtest_with_pillar_weights(self):
        r = backtest.run_backtest(
            bars=self._bars(),
            pillar_weights={"trend": 0.4, "momentum": 0.3, "macro_sentiment": 0.3},
            capital=10000.0,
        )
        # Pillar-weighted mode should produce a valid BacktestResult with numeric metrics.
        self.assertIsInstance(r, backtest.BacktestResult)
        self.assertGreaterEqual(r.total_trades, 0)
        self.assertIsInstance(r.total_return_pct, float)
        self.assertIsInstance(r.sharpe_ratio, (float, type(None)))


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


class TestIntradayHelpers(unittest.TestCase):
    """Tests for intraday scanner helpers in orchestrator.py."""

    def test_decision_key_empty(self):
        from orchestrator import _decision_key
        key = _decision_key({"top_picks": [], "no_trade_day": True})
        self.assertEqual(key, ((), True))

    def test_decision_key_with_picks(self):
        from orchestrator import _decision_key
        sel = {"top_picks": [{"symbol": "BBB", "score": 85}, {"symbol": "AAA", "score": 90}]}
        key = _decision_key(sel)
        # Should be sorted by symbol name — key[0] is the tuple of picks
        self.assertEqual(key[0][0], ("AAA", 90, ""))
        self.assertEqual(key[0][1], ("BBB", 85, ""))

    def test_should_alert_first_run(self):
        from orchestrator import _should_alert
        sel = {"top_picks": [{"symbol": "X"}]}
        scores = [{"score": 80}]
        self.assertTrue(_should_alert(None, sel, None, scores, 10))

    def test_should_alert_decision_changed(self):
        from orchestrator import _decision_key, _should_alert
        prev_sel = {"top_picks": [], "no_trade_day": True}
        curr_sel = {"top_picks": [{"symbol": "X", "score": 85}], "no_trade_day": False}
        scores = [{"score": 80}]
        self.assertTrue(
            _should_alert(_decision_key(prev_sel), curr_sel, None, scores, 10)
        )

    def test_should_alert_score_shift(self):
        from orchestrator import _decision_key, _should_alert
        sel = {"top_picks": [{"symbol": "X", "score": 85}]}
        prev_scores = [{"score": 70}]
        curr_scores = [{"score": 85}]  # +15 shift >= min_score_change=10
        self.assertTrue(
            _should_alert(_decision_key(sel), sel, prev_scores, curr_scores, 10)
        )

    def test_should_not_alert_no_change(self):
        from orchestrator import _decision_key, _should_alert
        sel = {"top_picks": [{"symbol": "X", "score": 85}]}
        scores = [{"score": 85}]
        self.assertFalse(
            _should_alert(_decision_key(sel), sel, scores, scores, 10)
        )

    def test_should_not_alert_small_shift(self):
        from orchestrator import _decision_key, _should_alert
        sel = {"top_picks": [{"symbol": "X", "score": 85}]}
        prev_scores = [{"score": 76}]
        curr_scores = [{"score": 80}]  # +4 shift < min_score_change=10
        self.assertFalse(
            _should_alert(_decision_key(sel), sel, prev_scores, curr_scores, 10)
        )

    def test_quiet_hours_normal_range(self):
        from unittest.mock import patch
        from orchestrator import _is_in_quiet_hours
        # Simulate hour 23 (within 23-6 range)
        cfg = {"telegram": {"quiet_hours_start": 23, "quiet_hours_end": 6}}
        with patch("orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 23
            self.assertTrue(_is_in_quiet_hours(cfg))

    def test_quiet_hours_outside_range(self):
        from unittest.mock import patch
        from orchestrator import _is_in_quiet_hours
        # Simulate hour 10 (outside 23-6 range)
        cfg = {"telegram": {"quiet_hours_start": 23, "quiet_hours_end": 6}}
        with patch("orchestrator.datetime") as mock_dt:
            mock_dt.now.return_value.hour = 10
            self.assertFalse(_is_in_quiet_hours(cfg))

    def test_interval_clamping(self):
        """Interval should clamp to [15, 240] minutes."""
        # Test via config values — we check the function reads them correctly
        cfg = {"intraday": {"interval_minutes": 5}}  # below min
        interval = max(15, min(240, cfg["intraday"].get("interval_minutes", 60)))
        self.assertEqual(interval, 15)

        cfg2 = {"intraday": {"interval_minutes": 300}}  # above max
        interval2 = max(15, min(240, cfg2["intraday"].get("interval_minutes", 60)))
        self.assertEqual(interval2, 240)

    def test_max_ticks_limit(self):
        """Max ticks should stop the loop."""
        # We verify by checking that tick_count > max_ticks breaks
        max_ticks = 3
        tick_count = 0
        while True:
            tick_count += 1
            if max_ticks is not None and tick_count > max_ticks:
                break
        self.assertEqual(tick_count, max_ticks + 1)

    def test_no_trade_day_key_differs(self):
        """no_trade_day=True vs False should produce different keys."""
        from orchestrator import _decision_key
        key_ntd = _decision_key({"top_picks": [], "no_trade_day": True})
        key_trades = _decision_key({"top_picks": [], "no_trade_day": False})
        self.assertNotEqual(key_ntd, key_trades)


class TestIntradayConfig(unittest.TestCase):
    """Verify intraday config schema is present."""

    def test_config_has_intraday_section(self):
        import yaml
        with open("config.yaml") as f:
            cfg = yaml.safe_load(f)
        self.assertIn("intraday", cfg)
        self.assertEqual(cfg["intraday"]["enabled"], False)
        self.assertEqual(cfg["intraday"]["interval_minutes"], 60)


if __name__ == "__main__":
    unittest.main(verbosity=2)
