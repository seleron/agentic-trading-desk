#!/usr/bin/env python3
"""
portfolio.py
============
Portfolio position tracker for BIST AI Trader v1.0.

Tracks individual positions with:
  - Entry price, quantity, average cost basis
  - Unrealized PnL and PnL% (with optional live price updates)
  - Position states: OPEN, CLOSED, PENDING
  - Partial fills and position scaling (add/reduce/close)
  - Portfolio-level summary with per-position detail

Database schema (SQLite):
  table positions:
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    state TEXT DEFAULT 'PENDING',        -- PENDING | OPEN | CLOSED
    direction TEXT DEFAULT 'long',       -- long | short
    entry_price REAL NOT NULL,           -- original / weighted average entry
    quantity REAL NOT NULL,              -- current open quantity (signed)
    avg_cost REAL NOT NULL,             -- weighted average cost per unit
    total_invested REAL DEFAULT 0,      -- cumulative amount invested
    realized_pnl REAL DEFAULT 0,        -- cumulative closed-lot PnL
    date_opened TEXT,                   -- ISO date of first fill
    date_closed TEXT,                   -- ISO date when fully closed
    notes TEXT,                         -- free-form notes

  table fills:
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id INTEGER REFERENCES positions(id),
    fill_date TEXT NOT NULL,
    action TEXT NOT NULL,               -- BUY | SELL (partial close)
    price REAL NOT NULL,
    quantity REAL NOT NULL,             -- signed; positive=buy/add, negative=sell/reduce
    side TEXT DEFAULT 'long',           -- long | short (for fill-level PnL calc)

  table portfolio_config:
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL

Usage:
    python3 scripts/portfolio.py --init-db
    python3 scripts/portfolio.py --open-position "BIST:THYAO" --entry-price 120.5 --quantity 100
    python3 scripts/portfolio.py --add-position <position_id> --price 125.0 --quantity 50
    python3 scripts/portfolio.py --reduce-position <position_id> --price 130.0 --quantity 30
    python3 scripts/portfolio.py --close-position <position_id> --price 135.0
    python3 scripts/portfolio.py --set-config max_position_pct=20
    python3 scripts/portfolio.py --report [--date YYYY-MM-DD]

Non-blocking: all public functions accept a db_path and return gracefully on errors.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass
from datetime import date as date_type
from typing import Optional

# ── Database paths ──────────────────────────────────────────────────────────────

_DEFAULT_PORTFOLIO_DB = os.path.join(
    os.environ.get("HOME", ""),
    ".local", "share", "agentic-trading-desk", "portfolio.db"
)

_EOD_TRADES_DB = os.path.join(os.path.dirname(__file__), "..", "data", "trades.db")


# ── Data classes ────────────────────────────────────────────────────────────────

@dataclass
class PositionSummary:
    """Lightweight summary for a single position."""
    id: int
    symbol: str
    state: str
    direction: str
    quantity: float
    avg_cost: float
    entry_price: float
    current_price: Optional[float] = None  # set externally via update_live_prices()
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    total_invested: float = 0.0
    date_opened: Optional[str] = None


@dataclass
class PortfolioReport:
    """Full portfolio report."""
    date: str
    positions: list[dict]          # per-position summaries
    cash_balance: float = 0.0      # optional, set by caller
    total_invested: float = 0.0    # sum of avg_cost * quantity for OPEN positions
    total_realized_pnl: float = 0.0
    total_unrealized_pnl: float = 0.0
    portfolio_value: float = 0.0   # cash + invested + unrealized
    return_pct: float = 0.0        # (portfolio_value - initial_capital) / initial_capital * 100
    position_count: int = 0
    open_position_count: int = 0
    closed_position_count: int = 0


# ── Database helpers ────────────────────────────────────────────────────────────

def _get_portfolio_db_path(db_path: str | None = None) -> str:
    """Resolve portfolio DB path, creating parent dirs."""
    if db_path is None:
        db_path = _DEFAULT_PORTFOLIO_DB
    try:
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
    except OSError:
        pass  # Non-blocking: proceed even if we can't create the directory
    return db_path


def init_db(db_path: str | None = None) -> sqlite3.Connection:
    """Initialize the portfolio SQLite database. Returns a connection."""
    path = _get_portfolio_db_path(db_path)

    try:
        conn = sqlite3.connect(path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")

        conn.execute("""
            CREATE TABLE IF NOT EXISTS positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                symbol TEXT NOT NULL,
                state TEXT DEFAULT 'PENDING' CHECK(state IN ('PENDING','OPEN','CLOSED')),
                direction TEXT DEFAULT 'long' CHECK(direction IN ('long','short')),
                entry_price REAL NOT NULL,
                quantity REAL NOT NULL,
                avg_cost REAL NOT NULL,
                total_invested REAL DEFAULT 0,
                realized_pnl REAL DEFAULT 0,
                date_opened TEXT,
                date_closed TEXT,
                notes TEXT
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS fills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                position_id INTEGER REFERENCES positions(id),
                fill_date TEXT NOT NULL,
                action TEXT NOT NULL CHECK(action IN ('BUY','SELL')),
                price REAL NOT NULL,
                quantity REAL NOT NULL,   -- signed: positive=buy/add, negative=sell/reduce
                side TEXT DEFAULT 'long' CHECK(side IN ('long','short'))
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_config (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        conn.commit()
    except Exception:
        # Non-blocking fallback: in-memory DB with row_factory and tables created
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS positions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT NOT NULL, state TEXT DEFAULT 'PENDING',
                    direction TEXT DEFAULT 'long', entry_price REAL NOT NULL,
                    quantity REAL NOT NULL, avg_cost REAL NOT NULL,
                    total_invested REAL DEFAULT 0, realized_pnl REAL DEFAULT 0,
                    date_opened TEXT, date_closed TEXT, notes TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS fills (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    position_id INTEGER REFERENCES positions(id),
                    fill_date TEXT NOT NULL, action TEXT NOT NULL,
                    price REAL NOT NULL, quantity REAL NOT NULL,
                    side TEXT DEFAULT 'long'
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS portfolio_config (
                    key TEXT PRIMARY KEY, value TEXT NOT NULL
                )
            """)
        except Exception:
            pass  # Best effort; queries will return empty results

    return conn


def _safe_conn(db_path: str | None = None) -> sqlite3.Connection:
    """Get connection, init if needed. Caller must close."""
    try:
        return init_db(db_path)
    except Exception as e:
        print(f"[WARNING] portfolio DB init failed: {e}", file=sys.stderr)
        # Return a dummy connection that won't crash callers
        conn = sqlite3.connect(":memory:")
        conn.row_factory = sqlite3.Row
        return conn


# ── Core operations ─────────────────────────────────────────────────────────────

def open_position(
    symbol: str,
    entry_price: float,
    quantity: float,
    direction: str = "long",
    notes: str = "",
    db_path: str | None = None,
) -> PositionSummary:
    """
    Open a new position (first fill).

    Args:
        symbol: Ticker/symbol identifier.
        entry_price: Price per unit at opening.
        quantity: Number of units to buy (must be > 0).
        direction: 'long' or 'short'.
        notes: Optional free-form note.
        db_path: SQLite path (default: ~/.local/share/agentic-trading-desk/portfolio.db).

    Returns:
        PositionSummary for the newly opened position.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if entry_price <= 0:
        raise ValueError("entry_price must be positive")

    conn = init_db(db_path)
    today = date_type.today().isoformat()

    cursor = conn.execute(
        """INSERT INTO positions (symbol, state, direction, entry_price, quantity,
           avg_cost, total_invested, date_opened, notes)
           VALUES (?, 'OPEN', ?, ?, ?, ?, ?, ?, ?)""",
        (symbol, direction, entry_price, quantity, entry_price,
         entry_price * quantity, today, notes),
    )
    position_id = cursor.lastrowid if cursor.lastrowid is not None else 0

    conn.execute(
        "INSERT INTO fills (position_id, fill_date, action, price, quantity, side) "
        "VALUES (?, ?, 'BUY', ?, ?, ?)",
        (position_id, today, entry_price, quantity, direction),
    )

    conn.commit()
    conn.close()

    return PositionSummary(
        id=position_id, symbol=symbol, state="OPEN", direction=direction,
        quantity=quantity, avg_cost=entry_price, entry_price=entry_price,
        total_invested=entry_price * quantity, date_opened=today,
    )


def add_to_position(
    position_id: int,
    price: float,
    quantity: float,
    db_path: str | None = None,
) -> PositionSummary:
    """
    Add to an existing open position (scaling up).

    Updates the weighted average cost basis.

    Args:
        position_id: ID of the position to add to.
        price: Price per unit for this fill.
        quantity: Number of units to add (must be > 0).
        db_path: SQLite path override.

    Returns:
        Updated PositionSummary.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")
    if price <= 0:
        raise ValueError("price must be positive")

    conn = init_db(db_path)

    pos = conn.execute(
        "SELECT * FROM positions WHERE id = ? AND state = 'OPEN'", (position_id,)
    ).fetchone()
    if not pos:
        conn.close()
        raise ValueError(f"Position {position_id} not found or not OPEN")

    old_qty = pos["quantity"]
    old_cost = pos["avg_cost"]
    new_avg_cost = ((old_qty * old_cost) + (quantity * price)) / (old_qty + quantity)
    new_total_invested = new_avg_cost * (old_qty + quantity)

    today = date_type.today().isoformat()

    conn.execute(
        "UPDATE positions SET quantity = ?, avg_cost = ?, total_invested = ? WHERE id = ?",
        (old_qty + quantity, new_avg_cost, new_total_invested, position_id),
    )
    conn.execute(
        "INSERT INTO fills (position_id, fill_date, action, price, quantity, side) "
        "VALUES (?, ?, 'BUY', ?, ?, ?)",
        (position_id, today, price, quantity, pos["direction"]),
    )

    conn.commit()

    # Fetch updated position using same connection (tables exist, no re-open needed)
    result = _fetch_position_summary(conn, position_id)
    conn.close()
    return result


def reduce_position(
    position_id: int,
    price: float,
    quantity: float,
    db_path: str | None = None,
) -> PositionSummary:
    """
    Reduce an existing open position (partial close).

    Calculates realized PnL for the reduced portion. Cost basis stays unchanged.

    Args:
        position_id: ID of the position to reduce.
        price: Exit price per unit.
        quantity: Number of units to sell (must be > 0, <= current open qty).
        db_path: SQLite path override.

    Returns:
        Updated PositionSummary.
    """
    if quantity <= 0:
        raise ValueError("quantity must be positive")

    conn = init_db(db_path)

    pos = conn.execute(
        "SELECT * FROM positions WHERE id = ? AND state = 'OPEN'", (position_id,)
    ).fetchone()
    if not pos:
        conn.close()
        raise ValueError(f"Position {position_id} not found or not OPEN")

    open_qty = pos["quantity"]
    if quantity > open_qty + 1e-9:  # small epsilon for float comparison
        conn.close()
        raise ValueError(
            f"Cannot reduce {quantity} units; only {open_qty} open"
        )

    today = date_type.today().isoformat()

    # Realized PnL for this partial close
    if pos["direction"] == "long":
        realized_for_fill = (price - pos["avg_cost"]) * quantity
    else:  # short
        realized_for_fill = (pos["avg_cost"] - price) * quantity

    new_qty = open_qty - quantity
    conn.execute(
        "UPDATE positions SET quantity = ?, realized_pnl = ? WHERE id = ?",
        (new_qty, pos["realized_pnl"] + realized_for_fill, position_id),
    )
    conn.execute(
        "INSERT INTO fills (position_id, fill_date, action, price, quantity, side) "
        "VALUES (?, ?, 'SELL', ?, ?, ?)",
        (position_id, today, price, -quantity, pos["direction"]),
    )

    if new_qty < 1e-9:  # fully closed
        conn.execute(
            "UPDATE positions SET state = 'CLOSED', date_closed = ? WHERE id = ?",
            (today, position_id),
        )

    conn.commit()

    # Fetch updated position using same connection
    result = _fetch_position_summary(conn, position_id)
    conn.close()
    return result


def close_position(
    position_id: int,
    price: float,
    db_path: str | None = None,
) -> PositionSummary:
    """
    Fully close an open position.

    Args:
        position_id: ID of the position to close.
        price: Exit price per unit.
        db_path: SQLite path override.

    Returns:
        Updated PositionSummary (state=CLOSED).
    """
    conn = init_db(db_path)

    pos = conn.execute(
        "SELECT * FROM positions WHERE id = ? AND state = 'OPEN'", (position_id,)
    ).fetchone()
    if not pos:
        conn.close()
        raise ValueError(f"Position {position_id} not found or not OPEN")

    today = date_type.today().isoformat()
    qty = pos["quantity"]

    # Realized PnL
    if pos["direction"] == "long":
        realized = (price - pos["avg_cost"]) * qty
    else:  # short
        realized = (pos["avg_cost"] - price) * qty

    conn.execute(
        """UPDATE positions SET state = 'CLOSED', quantity = 0,
           realized_pnl = ?, date_closed = ? WHERE id = ?""",
        (pos["realized_pnl"] + realized, today, position_id),
    )
    conn.execute(
        "INSERT INTO fills (position_id, fill_date, action, price, quantity, side) "
        "VALUES (?, ?, 'SELL', ?, ?, ?)",
        (position_id, today, price, -qty, pos["direction"]),
    )

    conn.commit()

    # Fetch updated position using same connection
    result = _fetch_position_summary(conn, position_id)
    conn.close()
    return result


def set_config(key: str, value: str, db_path: str | None = None) -> None:
    """Set a portfolio configuration value."""
    conn = init_db(db_path)
    conn.execute(
        "INSERT OR REPLACE INTO portfolio_config (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()
    conn.close()


def get_config(key: str, default: str | None = None, db_path: str | None = None) -> str | None:
    """Get a portfolio configuration value."""
    try:
        conn = init_db(db_path)
    except Exception:
        return default

    row = conn.execute(
        "SELECT value FROM portfolio_config WHERE key = ?", (key,)
    ).fetchone()
    conn.close()

    if row is None:
        return default
    return str(row["value"])


def get_max_position_pct(db_path: str | None = None) -> float:
    """Get configured max position size as percentage of capital (default 20%)."""
    raw = get_config("max_position_pct", "20", db_path) or "20"
    try:
        return float(raw)
    except (ValueError, TypeError):
        return 20.0


# ── Position lookup & summary ───────────────────────────────────────────────────

def _fetch_position_summary(conn: sqlite3.Connection, position_id: int) -> PositionSummary:
    """Fetch a single position as a dataclass."""
    row = conn.execute(
        "SELECT * FROM positions WHERE id = ?", (position_id,)
    ).fetchone()
    if not row:
        raise ValueError(f"Position {position_id} not found")

    return PositionSummary(
        id=row["id"], symbol=row["symbol"], state=row["state"],
        direction=row["direction"], quantity=row["quantity"],
        avg_cost=row["avg_cost"], entry_price=row["entry_price"],
        realized_pnl=row["realized_pnl"] or 0.0,
        total_invested=row["total_invested"] or 0.0,
        date_opened=row["date_opened"],
    )


def get_position(position_id: int, db_path: str | None = None) -> PositionSummary:
    """Get a single position by ID."""
    conn = init_db(db_path)
    try:
        return _fetch_position_summary(conn, position_id)
    finally:
        conn.close()


def list_positions(
    state: str | None = None,
    symbol: str | None = None,
    db_path: str | None = None,
) -> list[PositionSummary]:
    """List positions with optional filters."""
    conn = init_db(db_path)

    query = "SELECT * FROM positions"
    conditions = []
    params = []

    if state:
        conditions.append("state = ?")
        params.append(state)
    if symbol:
        conditions.append("LOWER(symbol) LIKE LOWER(?)")
        params.append(f"%{symbol}%")

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    rows = conn.execute(query, params).fetchall()
    conn.close()

    return [PositionSummary(
        id=r["id"], symbol=r["symbol"], state=r["state"],
        direction=r["direction"], quantity=r["quantity"],
        avg_cost=r["avg_cost"], entry_price=r["entry_price"],
        realized_pnl=r["realized_pnl"] or 0.0,
        total_invested=r["total_invested"] or 0.0,
        date_opened=r["date_opened"],
    ) for r in rows]


def update_live_prices(
    positions: list[PositionSummary],
    price_map: dict[str, float],
) -> list[PositionSummary]:
    """
    Update unrealized PnL on positions using live prices.

    Args:
        positions: List of PositionSummary objects (from get/list calls).
        price_map: Mapping from symbol to current market price.

    Returns:
        Same list with unrealized_pnl and unrealized_pnl_pct populated.
    """
    for pos in positions:
        sym = pos.symbol.upper()
        live_price = price_map.get(sym) or price_map.get(pos.symbol)
        if live_price is None or live_price <= 0:
            pos.current_price = None
            pos.unrealized_pnl = 0.0
            pos.unrealized_pnl_pct = 0.0
            continue

        pos.current_price = live_price

        if pos.direction == "long":
            pnl = (live_price - pos.avg_cost) * pos.quantity
        else:  # short
            pnl = (pos.avg_cost - live_price) * pos.quantity

        pos.unrealized_pnl = round(pnl, 2)
        if pos.avg_cost > 0 and pos.quantity != 0:
            pos.unrealized_pnl_pct = round((pnl / (abs(pos.avg_cost * pos.quantity))) * 100, 2)
        else:
            pos.unrealized_pnl_pct = 0.0

    return positions


# ── Integration with trade_plan.py ──────────────────────────────────────────────

def create_position_from_trade_plan(
    plan: dict,
    capital: float = 10000.0,
    db_path: str | None = None,
) -> PositionSummary:
    """
    Auto-create a position from an approved trade plan (trade_plan.py output).

    Args:
        plan: Trade plan dict with 'symbol', 'entry.price', 'position_size', etc.
        capital: Total trading capital for max-position-size check.
        db_path: SQLite path override.

    Returns:
        PositionSummary of the created position.
    """
    symbol = plan.get("symbol", "UNKNOWN")
    entry_price = plan["entry"]["price"]
    direction = plan.get("direction", "long")
    quantity = plan.get("position_size", 0)

    if quantity <= 0:
        raise ValueError(f"Position size {quantity} from trade plan is non-positive")

    # Check max position size constraint
    max_pct = get_max_position_pct(db_path)
    current_exposure = _total_open_exposure(db_path)
    new_investment = entry_price * quantity
    total_after = current_exposure + new_investment
    effective_capital = capital - current_exposure  # remaining available

    if effective_capital > 0:
        pct_of_remaining = (new_investment / effective_capital) * 100
    else:
        pct_of_remaining = 0.0

    max_allowed_value = capital * (max_pct / 100.0)
    if total_after > max_allowed_value:
        # Cap position to stay within limits
        remaining_room = max_allowed_value - current_exposure
        quantity = min(quantity, remaining_room / entry_price) if entry_price > 0 else quantity

    notes = f"Auto-created from trade plan. Rationale: {plan.get('entry', {}).get('rationale', '')}"

    return open_position(
        symbol=symbol,
        entry_price=entry_price,
        quantity=quantity,
        direction=direction,
        notes=notes,
        db_path=db_path,
    )


def _total_open_exposure(db_path: str | None = None) -> float:
    """Calculate total current exposure for OPEN positions."""
    try:
        conn = init_db(db_path)
    except Exception:
        return 0.0

    rows = conn.execute(
        "SELECT quantity, avg_cost FROM positions WHERE state = 'OPEN'"
    ).fetchall()
    conn.close()

    return sum(abs(r["quantity"] * r["avg_cost"]) for r in rows)


# ── Portfolio report ────────────────────────────────────────────────────────────

def generate_portfolio_report(
    db_path: str | None = None,
    price_map: dict[str, float] | None = None,
    capital: float = 0.0,
    initial_capital: float | None = None,
) -> PortfolioReport:
    """
    Generate a comprehensive portfolio report.

    Args:
        db_path: SQLite path override.
        price_map: Optional live prices for unrealized PnL calculation.
        capital: Current cash balance (0 if unknown).
        initial_capital: Starting capital for return-calculation (default=capital).

    Returns:
        PortfolioReport dataclass.
    """
    positions = list_positions(db_path=db_path)

    # Update live prices if provided
    if price_map:
        update_live_prices(positions, price_map)

    total_realized = sum(p.realized_pnl for p in positions)
    total_unrealized = sum(p.unrealized_pnl_pct * (abs(p.avg_cost * p.quantity)) / 100
                       for p in positions if p.current_price is not None and p.state == "OPEN")

    # Recalculate unrealized more precisely
    total_unrealized = 0.0
    for p in positions:
        if p.current_price is not None and p.state == "OPEN" and p.quantity != 0:
            if p.direction == "long":
                pnl = (p.current_price - p.avg_cost) * p.quantity
            else:
                pnl = (p.avg_cost - p.current_price) * p.quantity
            total_unrealized += pnl

    # Only count OPEN positions for exposure
    open_positions = [p for p in positions if p.state == "OPEN"]
    closed_positions = [p for p in positions if p.state == "CLOSED"]
    pending_positions = [p for p in positions if p.state == "PENDING"]

    total_invested = sum(abs(p.avg_cost * p.quantity) for p in open_positions)
    portfolio_value = capital + total_invested + total_unrealized

    init_cap = initial_capital if initial_capital is not None else (capital + total_invested)
    return_pct = ((portfolio_value - init_cap) / init_cap * 100) if init_cap > 0 else 0.0

    # Build position dicts for JSON serialization
    pos_dicts = []
    for p in positions:
        d = {
            "id": p.id,
            "symbol": p.symbol,
            "state": p.state,
            "direction": p.direction,
            "quantity": round(p.quantity, 6),
            "avg_cost": round(p.avg_cost, 6),
            "entry_price": round(p.entry_price, 6),
            "realized_pnl": round(p.realized_pnl, 2),
        }
        if p.current_price is not None:
            d["current_price"] = round(p.current_price, 6)
            d["unrealized_pnl"] = round(p.unrealized_pnl, 2)
            d["unrealized_pnl_pct"] = round(p.unrealized_pnl_pct, 2)
        if p.date_opened:
            d["date_opened"] = p.date_opened
        pos_dicts.append(d)

    return PortfolioReport(
        date=date_type.today().isoformat(),
        positions=pos_dicts,
        cash_balance=capital,
        total_invested=round(total_invested, 2),
        total_realized_pnl=round(total_realized, 2),
        total_unrealized_pnl=round(total_unrealized, 2),
        portfolio_value=round(portfolio_value, 2),
        return_pct=round(return_pct, 2),
        position_count=len(positions),
        open_position_count=len(open_positions),
        closed_position_count=len(closed_positions),
    )


# ── CLI entry point ─────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Portfolio position tracker for BIST AI Trader v1.0."
    )
    ap.add_argument("--db", default=None, help="SQLite database path")
    ap.add_argument("--init-db", action="store_true", help="Initialize the portfolio DB")

    # Position actions
    sub = ap.add_subparsers(dest="command", help="Action to perform")

    open_parser = sub.add_parser("open-position", help="Open a new position")
    open_parser.add_argument("--symbol", required=True, help="Ticker symbol")
    open_parser.add_argument("--entry-price", type=float, required=True)
    open_parser.add_argument("--quantity", type=float, required=True, help="Number of units")
    open_parser.add_argument("--direction", default="long", choices=["long", "short"])
    open_parser.add_argument("--notes", default="", help="Optional notes")

    add_parser = sub.add_parser("add-position", help="Add to existing position (scale up)")
    add_parser.add_argument("--position-id", type=int, required=True)
    add_parser.add_argument("--price", type=float, required=True)
    add_parser.add_argument("--quantity", type=float, required=True)

    reduce_parser = sub.add_parser("reduce-position", help="Reduce existing position (partial close)")
    reduce_parser.add_argument("--position-id", type=int, required=True)
    reduce_parser.add_argument("--price", type=float, required=True)
    reduce_parser.add_argument("--quantity", type=float, required=True)

    close_parser = sub.add_parser("close-position", help="Fully close a position")
    close_parser.add_argument("--position-id", type=int, required=True)
    close_parser.add_argument("--price", type=float, required=True)

    # Config actions
    config_parser = sub.add_parser("set-config", help="Set portfolio configuration")
    config_parser.add_argument("config", help="key=value pair (e.g., max_position_pct=20)")

    # Report
    report_parser = sub.add_parser("report", help="Generate full portfolio report")
    report_parser.add_argument("--price-map-file", default=None,
                                help="JSON file with live prices {symbol: price}")
    report_parser.add_argument("--capital", type=float, default=0.0, help="Current cash balance")
    report_parser.add_argument("--output", "-o", default=None)

    # List positions
    list_parser = sub.add_parser("list-positions", help="List all positions")
    list_parser.add_argument("--state", choices=["OPEN", "CLOSED", "PENDING"], default=None)
    list_parser.add_argument("--symbol", default=None, help="Filter by symbol (partial match)")

    args = ap.parse_args()

    if args.init_db:
        init_db(args.db)
        print(json.dumps({"status": "ok", "message": "Portfolio DB initialized"}, indent=2))
        return 0

    cmd = getattr(args, "command", None) or getattr(args, "cmd", None)

    try:
        if cmd == "open-position":
            pos = open_position(
                symbol=args.symbol, entry_price=args.entry_price, quantity=args.quantity,
                direction=args.direction, notes=args.notes, db_path=args.db,
            )
            print(json.dumps(asdict(pos), indent=2))

        elif cmd == "add-position":
            pos = add_to_position(args.position_id, args.price, args.quantity, db_path=args.db)
            print(json.dumps(asdict(pos), indent=2))

        elif cmd == "reduce-position":
            pos = reduce_position(args.position_id, args.price, args.quantity, db_path=args.db)
            print(json.dumps(asdict(pos), indent=2))

        elif cmd == "close-position":
            pos = close_position(args.position_id, args.price, db_path=args.db)
            print(json.dumps(asdict(pos), indent=2))

        elif cmd == "set-config":
            key, val = args.config.split("=", 1)
            set_config(key.strip(), val.strip(), db_path=args.db)
            print(json.dumps({"status": "ok", "key": key.strip(), "value": val.strip()}, indent=2))

        elif cmd == "report":
            price_map = {}
            if args.price_map_file:
                with open(args.price_map_file) as f:
                    price_map = json.load(f)

            report = generate_portfolio_report(
                db_path=args.db, price_map=price_map, capital=args.capital,
            )

            output = json.dumps(asdict(report), indent=2, ensure_ascii=False)
            if args.output:
                with open(args.output, "w") as f:
                    f.write(output)
                print(f"[OK] Report saved to {args.output}", file=sys.stderr)
            else:
                print(output)

        elif cmd == "list-positions":
            positions = list_positions(state=args.state, symbol=args.symbol, db_path=args.db)
            print(json.dumps([asdict(p) for p in positions], indent=2))

        else:
            ap.print_help()
            return 0

    except (ValueError, KeyError) as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"[ERROR] Unexpected error: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
