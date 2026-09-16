#!/usr/bin/env python3
"""
test_shipped_stop_method.py
===========================
Pins the shipped stop-loss method (PR #15, round-7 review).

The pre-#008 ``generate_trade_plan`` already preferred an ATR×2 stop whenever
``atr14`` was available, so the backlog-#008 feature must SHIP with ATR stops
enabled — shipping ``fixed_pct`` (a flat 5% stop) as the default would silently
regress existing orchestrator output from ATR-scaled stops to a flat 5% stop,
contradicting the PR's intent ("ATR-based dynamic stops and targets").

This test reads the repo's actual ``config.yaml`` (the file the orchestrator
passes to ``generate_trade_plan``) and asserts its resolved ``stop_loss_method``
is ``"atr"``. It fails if someone flips the config back to ``fixed_pct`` —
that is exactly the regression the review flagged, so the gate must reject it.
"""
from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from trade_plan import load_config, resolve_stop_settings  # noqa: E402
from trade_plan import DEFAULT_CONFIG_PATH  # noqa: E402


class TestShippedStopMethod(unittest.TestCase):
    def test_repo_config_ships_atr_stops(self):
        """The repo's config.yaml must resolve to ATR stops (not the legacy
        flat fixed_pct default), so orchestrator plans keep the historical
        ATR-preferred stop sizing."""
        cfg = load_config(DEFAULT_CONFIG_PATH)
        self.assertNotEqual(
            cfg, {},
            f"config.yaml not found/readable at {DEFAULT_CONFIG_PATH} — "
            "the shipped-stop guard can't verify the method",
        )
        resolved = resolve_stop_settings(cfg)
        self.assertEqual(
            resolved["stop_loss_method"],
            "atr",
            "config.yaml trade_plan.stop_loss_method regressed to "
            f"{resolved['stop_loss_method']!r}; the pre-#008 engine preferred "
            "ATR×2 stops, so #008 must ship with ATR stops enabled (PR #15 "
            "round-7 review). Set it back to 'atr'.",
        )

    def test_default_fallback_is_fixed_pct(self):
        """Safeguard for the guard above: with NO config, the code default must
        remain the conservative legacy fixed_pct. If this default is ever
        flipped to 'atr', the no-config path changes behaviour silently and the
        config.yaml test above can no longer distinguish 'shipped atr' from
        'default atr'."""
        resolved = resolve_stop_settings({})
        self.assertEqual(
            resolved["stop_loss_method"],
            "fixed_pct",
            "the no-config default must stay the legacy fixed_pct; ATR stops "
            "are an explicit config choice, not a code default",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
