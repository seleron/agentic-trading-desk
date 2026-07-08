#!/usr/bin/env python3
"""
test_trade_plan_robustness.py
=============================
generate_trade_plan must survive the indicator *warmup* state, where compute()
emits keys like `ema20_slope` / `rsi14` but sets them to None (short history).
The confidence block used `indicators.get("ema20_slope", 0) > 0`, and since the
key is present-but-None the default never applied, so `None > 0` raised TypeError
for any short-history symbol that had cleared its EMA20.

This is a bug *class* — a `.get(key, default)` guard is useless when the key is
always present but may be None. These tests pin the fix and exercise the None-laden
warmup path across the whole function.

Run:  python3 -m unittest scripts.test_trade_plan_robustness
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from trade_plan import generate_trade_plan  # noqa: E402

DECISION = {"action": "RE-ENTRY", "score": 82, "rationale": "top pick"}


class TestTradePlanWarmupIndicators(unittest.TestCase):
    def test_ema20_slope_none_does_not_crash(self):
        """The exact regression: price above a truthy EMA20 with a None slope."""
        ind = {"close": 100.0, "ema20": 90.0, "ema20_slope": None,
               "rsi14": 60.0, "atr14": 2.0, "bb_lower": 85.0}
        plan = generate_trade_plan("WARMUP", DECISION, ind)
        self.assertEqual(plan["symbol"], "WARMUP")
        self.assertEqual(plan["status"], "active_plan")
        self.assertIsInstance(plan["entry"]["confidence"], float)
        self.assertTrue(0.0 <= plan["entry"]["confidence"] <= 1.0)

    def test_all_warmup_indicators_none_but_price_present(self):
        """Every indicator None except a valid close+atr — must produce a plan, no crash."""
        ind = {k: None for k in (
            "ema20", "ema50", "ema200", "ema20_slope", "ema50_slope",
            "rsi14", "bb_lower", "bb_upper", "macd_line", "macd_signal")}
        ind["close"] = 100.0
        ind["atr14"] = 1.5
        plan = generate_trade_plan("ALLNONE", DECISION, ind)
        self.assertEqual(plan["status"], "active_plan")
        self.assertIsInstance(plan["entry"]["confidence"], float)

    def test_rsi_exactly_zero_treated_as_zero_not_default(self):
        """RSI 0.0 is falsy; the old `rsi14 or 50` would silently treat it as 50.
        With rsi=0 momentum is weak → low confidence, not the mid default."""
        weak = generate_trade_plan("RSI0", DECISION,
                                   {"close": 100.0, "ema20": 90.0, "ema20_slope": 1.0,
                                    "rsi14": 0.0, "atr14": 2.0, "bb_lower": 85.0})
        strong = generate_trade_plan("RSI70", DECISION,
                                     {"close": 100.0, "ema20": 90.0, "ema20_slope": 1.0,
                                      "rsi14": 70.0, "atr14": 2.0, "bb_lower": 85.0})
        # Same trend contribution; only RSI differs → weak must be < strong.
        self.assertLess(weak["entry"]["confidence"], strong["entry"]["confidence"])

    def test_short_direction_warmup_none_slope(self):
        ind = {"close": 100.0, "ema20": 110.0, "ema20_slope": None,
               "rsi14": None, "atr14": 2.0, "bb_upper": 115.0}
        plan = generate_trade_plan("SHORT", {"action": "SELL", "score": 20}, ind)
        self.assertEqual(plan["direction"], "short")
        self.assertGreater(plan["stop_loss"]["price"], plan["entry"]["price"])

    def test_missing_price_returns_error_not_crash(self):
        plan = generate_trade_plan("NOPRICE", DECISION, {})
        self.assertIn("error", plan)

    def test_non_entry_action_is_no_trade(self):
        plan = generate_trade_plan("EXIT", {"action": "EXIT", "rationale": "trim"},
                                   {"close": 100.0, "ema20": 90.0, "ema20_slope": None})
        self.assertEqual(plan["status"], "no_trade")


if __name__ == "__main__":
    unittest.main(verbosity=2)
