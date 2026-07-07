#!/usr/bin/env python3
"""
test_portfolio.py
=================
Unit tests for the portfolio position tracker module.

Covers:
  - Database initialization and schema
  - Opening, adding to, reducing, closing positions
  - Weighted average cost calculation on scale-up
  - Realized PnL on partial/full close (long and short)
  - Max position size enforcement
  - Portfolio report generation
  - Non-blocking DB access
  - CLI entry point

Run with:  python3 scripts/test_portfolio.py   (unittest — no external deps)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import portfolio


class TestDatabaseInit(unittest.TestCase):
    def test_init_creates_tables(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = f.name
        try:
            conn = portfolio.init_db(db)
            tables = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            table_names = {t["name"] for t in tables}
            self.assertIn("positions", table_names)
            self.assertIn("fills", table_names)
            self.assertIn("portfolio_config", table_names)
            conn.close()
        finally:
            os.unlink(db)

    def test_nonblocking_db(self):
        """Non-blocking: init should not crash on invalid but writable paths."""
        db = "/tmp/test_portfolio_nonblock.db"
        try:
            conn = portfolio.init_db(db)
            self.assertIsNotNone(conn)
            conn.close()
        finally:
            if os.path.exists(db):
                os.unlink(db)


class TestOpenPosition(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "test_port.db")

    def test_open_long_position(self):
        pos = portfolio.open_position("AAPL", 150.0, 100, direction="long", db_path=self.db)
        self.assertEqual(pos.symbol, "AAPL")
        self.assertEqual(pos.state, "OPEN")
        self.assertEqual(pos.direction, "long")
        self.assertEqual(pos.quantity, 100)
        self.assertEqual(pos.avg_cost, 150.0)

    def test_open_short_position(self):
        pos = portfolio.open_position("GOOG", 2800.0, 10, direction="short", db_path=self.db)
        self.assertEqual(pos.direction, "short")
        self.assertEqual(pos.quantity, 10)

    def test_open_rejects_zero_quantity(self):
        with self.assertRaises(ValueError):
            portfolio.open_position("X", 100.0, 0, db_path=self.db)

    def test_open_rejects_negative_price(self):
        with self.assertRaises(ValueError):
            portfolio.open_position("X", -5.0, 10, db_path=self.db)


class TestAddToPosition(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "test_port.db")

    def test_scale_up_weighted_avg(self):
        portfolio.open_position("AAPL", 150.0, 100, db_path=self.db)
        pos = portfolio.add_to_position(1, 160.0, 50, db_path=self.db)
        # Weighted avg: (100*150 + 50*160) / 150 = 23000/150 = 153.33...
        self.assertAlmostEqual(pos.avg_cost, 153.3333, places=4)
        self.assertEqual(pos.quantity, 150)

    def test_add_to_nonexistent(self):
        with self.assertRaises(ValueError):
            portfolio.add_to_position(999, 100.0, 10, db_path=self.db)


class TestReducePosition(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "test_port.db")

    def test_partial_close_long_realized_pnl(self):
        portfolio.open_position("AAPL", 150.0, 100, db_path=self.db)
        pos = portfolio.reduce_position(1, 170.0, 30, db_path=self.db)
        self.assertEqual(pos.quantity, 70)
        # Realized: (170-150)*30 = 600
        self.assertAlmostEqual(pos.realized_pnl, 600.0)

    def test_partial_close_short_realized_pnl(self):
        portfolio.open_position("GOOG", 2800.0, 10, direction="short", db_path=self.db)
        pos = portfolio.reduce_position(1, 2750.0, 3, db_path=self.db)
        self.assertEqual(pos.quantity, 7)
        # Short realized: (2800-2750)*3 = 150 profit
        self.assertAlmostEqual(pos.realized_pnl, 150.0)

    def test_reduce_to_zero_closes_position(self):
        portfolio.open_position("AAPL", 150.0, 100, db_path=self.db)
        pos = portfolio.reduce_position(1, 160.0, 100, db_path=self.db)
        self.assertEqual(pos.state, "CLOSED")


class TestClosePosition(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "test_port.db")

    def test_full_close_long(self):
        portfolio.open_position("AAPL", 150.0, 100, db_path=self.db)
        pos = portfolio.close_position(1, 180.0, db_path=self.db)
        self.assertEqual(pos.state, "CLOSED")
        # Realized: (180-150)*100 = 3000
        self.assertAlmostEqual(pos.realized_pnl, 3000.0)

    def test_full_close_short(self):
        portfolio.open_position("GOOG", 2800.0, 10, direction="short", db_path=self.db)
        pos = portfolio.close_position(1, 2700.0, db_path=self.db)
        self.assertEqual(pos.state, "CLOSED")
        # Short realized: (2800-2700)*10 = 1000 profit
        self.assertAlmostEqual(pos.realized_pnl, 1000.0)


class TestConfig(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "test_port.db")

    def test_set_and_get_config(self):
        portfolio.set_config("max_position_pct", "25", db_path=self.db)
        val = portfolio.get_config("max_position_pct", db_path=self.db)
        self.assertEqual(val, "25")

    def test_default_max_position_pct(self):
        pct = portfolio.get_max_position_pct(db_path=self.db)
        self.assertAlmostEqual(pct, 20.0)

    def test_custom_max_position_pct(self):
        portfolio.set_config("max_position_pct", "15", db_path=self.db)
        pct = portfolio.get_max_position_pct(db_path=self.db)
        self.assertAlmostEqual(pct, 15.0)


class TestListPositions(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "test_port.db")

    def test_list_all(self):
        portfolio.open_position("AAPL", 150.0, 100, db_path=self.db)
        portfolio.open_position("GOOG", 2800.0, 10, direction="short", db_path=self.db)
        positions = portfolio.list_positions(db_path=self.db)
        self.assertEqual(len(positions), 2)

    def test_filter_by_state(self):
        portfolio.open_position("AAPL", 150.0, 100, db_path=self.db)
        portfolio.close_position(1, 160.0, db_path=self.db)
        opened = portfolio.list_positions(state="OPEN", db_path=self.db)
        closed = portfolio.list_positions(state="CLOSED", db_path=self.db)
        self.assertEqual(len(opened), 0)
        self.assertEqual(len(closed), 1)

    def test_filter_by_symbol(self):
        portfolio.open_position("AAPL", 150.0, 100, db_path=self.db)
        portfolio.open_position("GOOG", 2800.0, 10, direction="short", db_path=self.db)
        aapl = portfolio.list_positions(symbol="AAPL", db_path=self.db)
        self.assertEqual(len(aapl), 1)
        self.assertEqual(aapl[0].symbol, "AAPL")


class TestUpdateLivePrices(unittest.TestCase):
    def test_long_unrealized_pnl(self):
        pos = portfolio.PositionSummary(
            id=1, symbol="AAPL", state="OPEN", direction="long",
            quantity=100, avg_cost=150.0, entry_price=150.0,
        )
        updated = portfolio.update_live_prices([pos], {"AAPL": 170.0})
        self.assertEqual(updated[0].current_price, 170.0)
        # Unrealized: (170-150)*100 = 2000
        self.assertAlmostEqual(updated[0].unrealized_pnl, 2000.0)

    def test_short_unrealized_pnl(self):
        pos = portfolio.PositionSummary(
            id=1, symbol="GOOG", state="OPEN", direction="short",
            quantity=10, avg_cost=2800.0, entry_price=2800.0,
        )
        updated = portfolio.update_live_prices([pos], {"GOOG": 2750.0})
        # Short unrealized: (2800-2750)*10 = 500 profit
        self.assertAlmostEqual(updated[0].unrealized_pnl, 500.0)

    def test_missing_price(self):
        pos = portfolio.PositionSummary(
            id=1, symbol="AAPL", state="OPEN", direction="long",
            quantity=100, avg_cost=150.0, entry_price=150.0,
        )
        updated = portfolio.update_live_prices([pos], {})
        self.assertIsNone(updated[0].current_price)


class TestCreatePositionFromTradePlan(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "test_port.db")

    def test_create_from_plan(self):
        plan = {
            "symbol": "AAPL",
            "direction": "long",
            "entry": {"price": 150.0, "rationale": "Bullish EMA crossover"},
            "position_size": 100,
        }
        pos = portfolio.create_position_from_trade_plan(plan, capital=100000.0, db_path=self.db)
        self.assertEqual(pos.symbol, "AAPL")
        self.assertEqual(pos.state, "OPEN")

    def test_max_position_cap(self):
        # Set max to 10% of capital = $10k
        portfolio.set_config("max_position_pct", "10", db_path=self.db)
        plan = {
            "symbol": "AAPL",
            "direction": "long",
            "entry": {"price": 150.0},
            "position_size": 200,  # Would be $30k, cap at $10k → ~66.67 units
        }
        pos = portfolio.create_position_from_trade_plan(plan, capital=100000.0, db_path=self.db)
        self.assertLessEqual(pos.avg_cost * pos.quantity, 10000.0 + 1.0)


class TestPortfolioReport(unittest.TestCase):
    def setUp(self):
        self.db = os.path.join(tempfile.mkdtemp(), "test_port.db")

    def test_empty_report(self):
        report = portfolio.generate_portfolio_report(db_path=self.db, capital=50000.0)
        self.assertEqual(report.position_count, 0)
        self.assertEqual(report.open_position_count, 0)

    def test_report_with_positions(self):
        portfolio.open_position("AAPL", 150.0, 100, db_path=self.db)
        report = portfolio.generate_portfolio_report(
            db_path=self.db, capital=50000.0, price_map={"AAPL": 170.0},
        )
        self.assertEqual(report.position_count, 1)
        self.assertEqual(report.open_position_count, 1)
        self.assertGreater(report.total_invested, 0)

    def test_report_with_closed_positions(self):
        portfolio.open_position("AAPL", 150.0, 100, db_path=self.db)
        portfolio.close_position(1, 180.0, db_path=self.db)
        report = portfolio.generate_portfolio_report(db_path=self.db, capital=50000.0)
        self.assertEqual(report.position_count, 1)
        self.assertEqual(report.closed_position_count, 1)
        self.assertEqual(report.open_position_count, 0)


class TestNonBlocking(unittest.TestCase):
    """Portfolio module should not crash scanner if DB is unavailable."""

    def test_list_from_unwritable_db(self):
        positions = portfolio.list_positions(db_path="/proc/99999/port.db")
        self.assertEqual(positions, [])

    def test_report_from_unwritable_db(self):
        report = portfolio.generate_portfolio_report(
            db_path="/proc/99999/port.db", capital=100.0,
        )
        self.assertEqual(report.position_count, 0)


class TestCLI(unittest.TestCase):
    """Test the CLI entry point via subprocess."""

    def _run_cli(self, args: list[str], input_data: str | None = None) -> tuple[int, str]:
        # Use direct script execution with PYTHONPATH set to parent dir
        repo_dir = Path(__file__).resolve().parent.parent
        env = os.environ.copy()
        env["PYTHONPATH"] = str(repo_dir) + ":" + env.get("PYTHONPATH", "")
        cmd = [sys.executable, "-m", "scripts.portfolio"] + args
        result = subprocess.run(
            cmd, capture_output=True, text=True, input=input_data, cwd=str(repo_dir),
            env=env,
        )
        return result.returncode, result.stdout + result.stderr

    def test_cli_open_position(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = f.name
        try:
            rc, out = self._run_cli(["--db", db, "open-position", "--symbol", "AAPL",
                                      "--entry-price", "150", "--quantity", "10"])
            self.assertEqual(rc, 0)
            data = json.loads(out.strip())
            self.assertEqual(data["symbol"], "AAPL")
        finally:
            os.unlink(db)

    def test_cli_report(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = f.name
        try:
            repo_dir = Path(__file__).resolve().parent.parent
            env = os.environ.copy()
            env["PYTHONPATH"] = str(repo_dir) + ":" + env.get("PYTHONPATH", "")
            # First open a position via CLI
            subprocess.run(
                [sys.executable, "-m", "scripts.portfolio", "--db", db, "open-position",
                 "--symbol", "AAPL", "--entry-price", "150", "--quantity", "10"],
                capture_output=True, text=True, cwd=str(repo_dir), env=env,
            )
            # Then generate report
            rc, out = self._run_cli(["--db", db, "report"])
            self.assertEqual(rc, 0)
            data = json.loads(out.strip())
            self.assertIn("positions", data)
        finally:
            os.unlink(db)

    def test_cli_set_config(self):
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db = f.name
        try:
            rc, out = self._run_cli(["--db", db, "set-config", "max_position_pct=30"])
            self.assertEqual(rc, 0)
        finally:
            os.unlink(db)


if __name__ == "__main__":
    unittest.main(verbosity=2)
