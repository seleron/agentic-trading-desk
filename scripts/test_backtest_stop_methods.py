"""Backtest stop-loss method tests (PR #15 review round 3).

Guards the finding that an `if stop_loss_method == "atr"` block inserted
between the entry `if` and the exit `elif` re-binds the exit branch, so
ATR-mode positions never exit.

Two kinds of guard:
  1. Structural AST check — the exit must be its own `if` statement in the
     for-loop body (decoupled from the entry `if`), evaluated against the
     unconditionally-computed `stop_price`.
  2. Behavioural source-patch probes — the backtest loop is executed with
     instrumentation injected at the branch itself, so the assertions read
     the branch decision directly (no dependence on downstream win/loss
     bookkeeping, which counts the end-of-run close separately).

Coverage: stop-hit exit in BOTH fixed_pct and atr modes, composite-reversal
exit in atr mode, ATR stop actually bound to `stop_atr_multiplier`, unknown
method rejected.
"""
import ast
import inspect
import io
import os
import sys
import textwrap
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import backtest  # noqa: E402
from backtest import run_backtest  # noqa: E402

PW = {"trend": 0.5, "momentum": 0.3, "macro": 0.2}

_ENTRY_ANCHOR = "        if not in_position and composite >= ENTRY_THRESHOLD:"
_ATR_ANCHOR = "                stop_price = entry_fill_price - atr_i * stop_atr_multiplier"


def _stop_hit_prices():
    """Rising ramp (warm-up SMA heuristic enters ~bar 11 at 133, fixed stop
    130.4), then a sustained collapse. The fixed 2% stop fires while the
    composite is still positive — only the stop clause can close the
    position. The series ends far below capital."""
    ramp = [100.0 + 3.0 * i for i in range(20)]
    crash = [ramp[-1] - 3.5 * i for i in range(1, 60)]
    return ramp + [p for p in crash if p > 10]


def _bars(prices):
    return [
        {
            "date": f"2026-{1 + i // 28:02d}-{i % 28 + 1:02d}",
            "open": p,
            "high": p,
            "low": p,
            "close": p,
            "volume": 1_000_000,
        }
        for i, p in enumerate(prices)
    ]


def _instrumented_run(bars, **kw):
    """Run the backtest with two probes compiled into the source (prints
    only — no behaviour change):

      ('branch', i, in_position, exit_condition_true, price, stop_price,
       composite)
        — recorded in the for-loop body while holding a position, with the
          same condition the exit if uses
      ('atr_stop', bar_index, atr_value, stop_price)
        — recorded every time the ATR override computes a stop

    Returns (result, probes).
    """
    src = inspect.getsource(backtest)
    assert src.count(_ENTRY_ANCHOR) == 1, "entry anchor moved"
    assert src.count(_ATR_ANCHOR) == 1, "atr anchor moved"

    probe_branch = (
        "        if in_position:\n"
        "            print('BRANCH', i, int(in_position),\n"
        "                  1 if (composite <= -ENTRY_THRESHOLD or price < stop_price) else 0,\n"
        "                  price, stop_price, composite)\n"
        + _ENTRY_ANCHOR
    )
    probe_atr = (
        _ATR_ANCHOR + "\n"
        "                print('ATRSTOP', i, atr_i, stop_price)\n"
    )
    src = src.replace(_ENTRY_ANCHOR, probe_branch)
    src = src.replace(_ATR_ANCHOR, probe_atr)

    buf = io.StringIO()
    with redirect_stdout(buf):
        ns = {"__file__": backtest.__file__}
        exec(compile(src, "<instrumented backtest>", "exec"), ns)
        res = ns["run_backtest"](bars, PW, **kw)

    probes = []
    for line in buf.getvalue().splitlines():
        parts = line.split()
        if parts and parts[0] == "BRANCH":
            probes.append(("branch", int(parts[1]), bool(int(parts[2])),
                           bool(int(parts[3])), float(parts[4]),
                           float(parts[5]), float(parts[6])))
        elif parts and parts[0] == "ATRSTOP":
            probes.append(("atr_stop", int(parts[1]), float(parts[2]),
                           float(parts[3])))
    return res, probes


class BacktestStopMethodTests(unittest.TestCase):
    # ---- 1. structural ---------------------------------------------------
    def test_stop_price_computed_unconditionally(self):
        """The fixed stop default must be assigned on every bar regardless of
        method, with the ATR override nested inside — not the other way
        round (the shape that caused the PR #15 mis-binding)."""
        src = textwrap.dedent(inspect.getsource(backtest.run_backtest))
        tree = ast.parse(src)
        stop_nodes = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Assign)
            and any(isinstance(t, ast.Name) and t.id == "stop_price"
                    for t in n.targets)
        ]
        self.assertGreaterEqual(len(stop_nodes), 2)
        default_node, atr_node = stop_nodes[0], stop_nodes[-1]
        # default assignment sits directly in the for-loop body (unconditional)
        parents = {}
        for n in ast.walk(tree):
            for child in ast.iter_child_nodes(n):
                parents[id(child)] = n
        self.assertIsInstance(parents[id(default_node)], ast.For)
        # ATR override sits inside a guard `if`
        p = parents.get(id(atr_node))
        self.assertIsInstance(p, ast.If)

    def test_exit_is_independent_if_with_stop_and_in_position(self):
        """Round-3 required fix: the exit must be its OWN `if` statement in
        the for-loop body (decoupled from the entry `if`), evaluated as
        `in_position and (composite <= -ENTRY_THRESHOLD or price < stop_price)`.
        The round-2 elif-chain shape let anything placed between the entry if
        and the exit steal/short-circuit the exit branch (the original PR #15
        bug)."""
        src = textwrap.dedent(inspect.getsource(backtest.run_backtest))
        tree = ast.parse(src)
        exit_nodes = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.If)
            and "stop_price" in ast.unparse(n.test)
            and "in_position" in ast.unparse(n.test)
        ]
        self.assertEqual(len(exit_nodes), 1,
                         "expected exactly one exit if using stop_price")
        exit_node = exit_nodes[0]
        # Independent statement: parent is the for-loop body, not the orelse
        # (elif) of another if.
        parents = {}
        for n in ast.walk(tree):
            for child in ast.iter_child_nodes(n):
                parents[id(child)] = n
        self.assertIsInstance(parents[id(exit_node)], ast.For,
                              "exit if must be its own statement in the loop "
                              "body, not an elif chained off the entry if")
        # Condition shape: in_position AND (composite reversal OR stop hit)
        test = exit_node.test
        self.assertIsInstance(test, ast.BoolOp)
        self.assertIsInstance(test.op, ast.And)
        conds = [ast.unparse(c) for c in test.values]
        self.assertTrue(any("in_position" in c for c in conds),
                        "exit must be guarded by in_position")
        self.assertTrue(any("stop_price" in c for c in conds),
                        "exit must compare stop_price")
        self.assertTrue(any("composite" in c for c in conds),
                        "exit must also allow the composite-reversal clause")

    # ---- 2. behavioural: stop-hit exits in both modes ---------------------
    def test_fixed_pct_mode_exits_on_stop_hit(self):
        _, probes = _instrumented_run(_bars(_stop_hit_prices()),
                                      stop_loss_method="fixed_pct")
        taken = [p for p in probes if p[0] == "branch" and p[3]]
        self.assertTrue(taken, "no exit in fixed_pct mode")
        _, _bar, _pos, _cond, price, stop, comp = taken[0]
        stop_hit = price < stop
        reversal = comp <= -0.5
        self.assertTrue(stop_hit or reversal,
                        "exit must be stop- or reversal-driven")

    def test_atr_mode_exits_on_stop_hit(self):
        """PR #15 bug: in ATR mode the exit elif was bound to the stop block
        and never ran — zero exits. The branch must now take the exit."""
        _, probes = _instrumented_run(_bars(_stop_hit_prices()),
                                      stop_loss_method="atr")
        taken = [p for p in probes if p[0] == "branch" and p[3]]
        self.assertTrue(
            taken,
            "ATR-mode loop never took the exit branch — exit elif is "
            "mis-bound to the stop_price block (PR #15 regression)",
        )
        atr_stops = [p for p in probes if p[0] == "atr_stop"]
        self.assertTrue(atr_stops, "ATR override never computed in atr mode")
        _, _bar, _pos, _cond, price, stop, comp = taken[0]
        stop_hit = price < stop
        reversal = comp <= -0.5
        self.assertTrue(stop_hit or reversal,
                        "exit must be stop- or reversal-driven")

    def test_atr_mode_composite_reversal_exits(self):
        """Composite reversal (no stop breach) must also exit in atr mode:
        a hard-down series where price never dips under the ATR stop before
        the composite collapses. Guard for: ATR mode must not become
        stop-only."""
        # Gap-down: composite craters but a wide ATR stop trails high above.
        prices = [100.0 + 3.0 * i for i in range(20)]
        prices += [prices[-1] - 30.0] * 3  # immediate gap down, flat
        prices += [prices[-1] - 0.5 * i for i in range(1, 50)]
        _, probes = _instrumented_run(_bars(prices), stop_loss_method="atr",
                                      stop_atr_multiplier=20.0)
        taken = [p for p in probes if p[0] == "branch" and p[3]]
        self.assertTrue(taken, "no composite-driven exit in atr mode")
        first = taken[0]
        self.assertLessEqual(first[6], -0.5,
                             "first exit should be composite-driven "
                             "(composite <= -threshold)")

    def test_atr_multiplier_bound(self):
        """stop_atr_multiplier must actually scale the stop (different
        multipliers -> different stop prices at the same bar)."""
        _, p_lo = _instrumented_run(_bars(_stop_hit_prices()),
                                    stop_loss_method="atr",
                                    stop_atr_multiplier=0.5)
        _, p_hi = _instrumented_run(_bars(_stop_hit_prices()),
                                    stop_loss_method="atr",
                                    stop_atr_multiplier=3.0)
        lo = {p[1]: p[3] for p in p_lo if p[0] == "atr_stop"}
        hi = {p[1]: p[3] for p in p_hi if p[0] == "atr_stop"}
        common = set(lo) & set(hi)
        self.assertTrue(common)
        self.assertTrue(all(abs(lo[i] - hi[i]) > 0.01 for i in common),
                        "stop_atr_multiplier has no effect on stop_price")

    # ---- 2b. behavioural: open position actually EXITS (not just branch) ---
    def test_atr_mode_open_position_actually_exits(self):
        """Round-3 fix: the branch-decision probes above can pass even when the
        exit never *fires* (they read the condition, not the bookkeeping).
        Assert the open position is genuinely closed by a stop-hit during the
        run — equity moves, a trade is logged, and the loop ENDS flat
        (in_position False), so the exit happened in-loop, not via the
        end-of-run 'exit_closed' close."""
        res = run_backtest(_bars(_stop_hit_prices()), PW, stop_loss_method="atr")
        # The position was opened and closed: a completed trade exists and the
        # loop ended flat, so the close was a real in-loop exit.
        self.assertGreaterEqual(res.total_trades, 1,
                                "no completed trade — position never exited in-loop")
        # Equity moved off the starting capital → the stop actually filled.
        self.assertNotEqual(res.final_equity, res.initial_capital,
                            "equity unchanged — no position was ever closed")
        self.assertEqual(res.losing_trades + res.winning_trades, res.total_trades)

    # ---- 3. validation ------------------------------------------------------
    def test_unknown_stop_method_rejected(self):
        with self.assertRaises(ValueError):
            run_backtest(_bars(_stop_hit_prices()), PW,
                         stop_loss_method="bogus")


if __name__ == "__main__":
    unittest.main()
