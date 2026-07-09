#!/usr/bin/env python3
"""
test_relative_strength.py
=========================
Acceptance tests for backlog 007 — the relative-strength-vs-benchmark modifier.

These assert the NUMERIC ±1 effect (not just types), because the whole point of
re-queuing 007 was that the previous attempt's modifier was a silent no-op. They
also lock the end-to-end wiring: score_quotes threading benchmark+threshold, and
run_full_pipeline accepting `args` (a NameError regression the first draft shipped).

Run:  python3 -m unittest scripts.test_relative_strength
"""
from __future__ import annotations

import inspect
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from scoring_engine import (  # noqa: E402
    compute_relative_strength,
    score_quote,
    score_quotes,
)
from test_pipeline import _bullish_quote  # noqa: E402


class TestComputeRelativeStrength(unittest.TestCase):
    def test_outperformance_gives_plus_one(self):
        rs = compute_relative_strength([100.0, 120.0], [100.0, 101.0], threshold=0.05)
        self.assertEqual(rs["direction"], 1)
        self.assertGreater(rs["ratio"], 1.0)

    def test_underperformance_gives_minus_one(self):
        rs = compute_relative_strength([100.0, 101.0], [100.0, 150.0], threshold=0.05)
        self.assertEqual(rs["direction"], -1)
        self.assertLess(rs["ratio"], 1.0)

    def test_within_threshold_is_neutral(self):
        # Stock +2%, benchmark +1% → ratio ~1.0099 < 1.05 → neutral.
        rs = compute_relative_strength([100.0, 102.0], [100.0, 101.0], threshold=0.05)
        self.assertEqual(rs["direction"], 0)

    def test_flat_benchmark_is_neutral_not_crash(self):
        rs = compute_relative_strength([100.0, 120.0], [100.0, 100.0], threshold=0.05)
        self.assertEqual(rs["direction"], 0)
        self.assertEqual(rs["benchmark_return_pct"], 0.0)

    def test_insufficient_data_returns_none(self):
        self.assertIsNone(compute_relative_strength([100.0], [100.0, 101.0]))
        self.assertIsNone(compute_relative_strength([100.0, 101.0], [101.0]))

    def test_zero_or_negative_start_returns_none(self):
        self.assertIsNone(compute_relative_strength([0.0, 120.0], [100.0, 101.0]))


class TestScoreQuoteModifierNumericEffect(unittest.TestCase):
    """The modifier must actually MOVE the final score — the anti-no-op guard."""

    def setUp(self):
        self.base = score_quote(_bullish_quote())["score"]

    def _quote_with_series(self):
        q = _bullish_quote()
        q["close_series"] = [100.0, 120.0]  # stock +20%
        return q

    def test_outperform_adds_exactly_one(self):
        s = score_quote(self._quote_with_series(), benchmark_closes=[100.0, 101.0])["score"]
        self.assertEqual(s, min(100, self.base + 1))

    def test_underperform_subtracts_exactly_one(self):
        s = score_quote(self._quote_with_series(), benchmark_closes=[100.0, 150.0])["score"]
        self.assertEqual(s, max(0, self.base - 1))

    def test_no_benchmark_leaves_score_unchanged(self):
        self.assertEqual(score_quote(_bullish_quote(), benchmark_closes=None)["score"], self.base)

    def test_benchmark_but_no_close_series_is_noop(self):
        # A benchmark without a per-stock close_series can't compute RS → unchanged.
        self.assertEqual(score_quote(_bullish_quote(), benchmark_closes=[100.0, 101.0])["score"], self.base)

    def test_relative_strength_field_populated(self):
        r = score_quote(self._quote_with_series(), benchmark_closes=[100.0, 101.0])
        self.assertIn("relative_strength", r)
        self.assertEqual(r["relative_strength"]["direction"], 1)

    def test_score_stays_clamped_0_100(self):
        # Even at the ceiling, +1 can't push score past 100.
        q = self._quote_with_series()
        r = score_quote(q, benchmark_closes=[100.0, 101.0])
        self.assertTrue(0 <= r["score"] <= 100)


class TestWiring(unittest.TestCase):
    def test_score_quotes_threads_benchmark_and_threshold(self):
        q = _bullish_quote()
        q["close_series"] = [100.0, 120.0]
        out = score_quotes([q], benchmark_closes=[100.0, 101.0], rs_threshold=0.05)
        self.assertEqual(out[0]["relative_strength"]["direction"], 1)

    def test_score_quotes_signature_accepts_rs_params(self):
        params = inspect.signature(score_quotes).parameters
        self.assertIn("benchmark_closes", params)
        self.assertIn("rs_threshold", params)

    def test_run_full_pipeline_accepts_args(self):
        # The first draft referenced `args` inside run_full_pipeline without a param
        # → NameError at runtime. Lock the fix.
        from orchestrator import run_full_pipeline
        self.assertIn("args", inspect.signature(run_full_pipeline).parameters)


if __name__ == "__main__":
    unittest.main(verbosity=2)
