#!/usr/bin/env python3
"""
test_indicators_robustness.py
=============================
Robustness tests for the indicator engine, targeting bug *classes* that recur:

  * forward_fill leading/middle/trailing gaps — the leading-gap branch used to
    back-fill from the wrong index (series[1]) and silently leave any leading run
    of length >= 2 unfilled, defeating the whole NaN-safe guarantee.
  * length contract: every series function must return a list the SAME length as
    its input (ema_series, rsi_wilder, calculate_atr) — calculate_atr's short path
    used to return len max(n, period+1).
  * calculate_atr must not substitute first_atr for a legitimately-zero prior ATR.

Run:  python3 -m unittest scripts.test_indicators_robustness
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from indicators import (  # noqa: E402
    forward_fill,
    calculate_atr,
    ema_series,
    rsi_wilder,
    compute,
)


class TestForwardFill(unittest.TestCase):
    def test_leading_gap_len1(self):
        filled, _ = forward_fill([None, 5.0, 6.0])
        self.assertEqual(filled, [5.0, 5.0, 6.0])

    def test_leading_gap_len2(self):
        # The exact regression: a 2-long leading gap must be filled, not left None.
        filled, _ = forward_fill([None, None, 5.0])
        self.assertEqual(filled, [5.0, 5.0, 5.0])

    def test_leading_gap_len3(self):
        filled, _ = forward_fill([None, None, None, 7.0, 8.0])
        self.assertEqual(filled, [7.0, 7.0, 7.0, 7.0, 8.0])

    def test_middle_gap_forward_fills(self):
        filled, _ = forward_fill([1.0, None, None, 4.0])
        self.assertEqual(filled, [1.0, 1.0, 1.0, 4.0])

    def test_trailing_gap_uses_last_known(self):
        filled, _ = forward_fill([1.0, 2.0, None])
        self.assertEqual(filled, [1.0, 2.0, 2.0])

    def test_gap_exceeding_max_left_unfilled_and_warns(self):
        filled, warnings = forward_fill([1.0, None, None, None, 5.0], max_gap=2)
        self.assertEqual(filled, [1.0, None, None, None, 5.0])
        self.assertTrue(warnings, "a gap exceeding max_gap must emit a warning")

    def test_all_none_stays_none_no_crash(self):
        filled, _ = forward_fill([None, None, None])
        self.assertEqual(filled, [None, None, None])

    def test_no_gaps_is_identity(self):
        filled, warnings = forward_fill([1.0, 2.0, 3.0])
        self.assertEqual(filled, [1.0, 2.0, 3.0])
        self.assertEqual(warnings, [])

    def test_does_not_mutate_input(self):
        src = [None, None, 5.0]
        forward_fill(src)
        self.assertEqual(src, [None, None, 5.0])


class TestLengthContracts(unittest.TestCase):
    def test_series_functions_return_input_length(self):
        for n in (0, 1, 5, 14, 15, 20, 25, 60):
            data = [float(i + 1) for i in range(n)]
            self.assertEqual(len(ema_series(data, 20)), n, f"ema_series n={n}")
            self.assertEqual(len(rsi_wilder(data, 14)), n, f"rsi_wilder n={n}")
            self.assertEqual(len(calculate_atr(data, data, data, 14)), n, f"calculate_atr n={n}")

    def test_calculate_atr_short_path_matches_input_length(self):
        # n < period+1 must still return exactly n entries (not max(n, period+1)).
        self.assertEqual(len(calculate_atr([1.0] * 5, [1.0] * 5, [1.0] * 5, 14)), 5)


class TestCalculateAtr(unittest.TestCase):
    def test_flat_bars_give_zero_atr_not_substituted(self):
        n = 20
        highs = lows = closes = [10.0] * n
        atr = calculate_atr(highs, lows, closes, 14)
        self.assertEqual(len(atr), n)
        # Every post-warmup value must be exactly 0.0 (true range is 0 on flat bars);
        # the old `out[i-1] or first_atr` still worked here only because first_atr==0.
        for v in atr[14:]:
            self.assertEqual(v, 0.0)

    def test_atr_positive_on_real_movement(self):
        highs = [10 + i * 0.5 for i in range(20)]
        lows = [9 + i * 0.5 for i in range(20)]
        closes = [9.5 + i * 0.5 for i in range(20)]
        atr = calculate_atr(highs, lows, closes, 14)
        self.assertIsNotNone(atr[-1])
        self.assertGreater(atr[-1], 0.0)


class TestComputeRobustness(unittest.TestCase):
    def test_compute_on_minimal_series_no_crash(self):
        # 25 flat-ish bars: warmup Nones abound, but compute must return a full dict.
        data = [100.0 + (i % 3) for i in range(25)]
        out = compute(data, highs=[d + 1 for d in data], lows=[d - 1 for d in data],
                      volumes=[1000] * len(data))
        for key in ("close", "ema20", "rsi14", "data_quality_warnings"):
            self.assertIn(key, out)
        # ema20 present (>=20 bars) and numeric; longer EMAs may be None — that's fine.
        self.assertIsNotNone(out["ema20"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
