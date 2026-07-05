#!/usr/bin/env python3
"""
eod_module.py
=============
End-of-Day module for BIST AI Trader v1.0.

Per spec:
  At 18:10, agent re-runs:
    - Calculates PnL on open positions
    - Records success/failure to database
    - Updates trade log

Database schema (SQLite):
  table trades:
    date TEXT, symbol TEXT, entry REAL, exit REAL, result TEXT, score INTEGER,
    pnl REAL, pnl_pct REAL, duration_bars INTEGER

Usage:
    python3 scripts/eod_module.py --trades trades.json --output eod_report.json
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sqlite3
import sys
from datetime import date as date_type


DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "trades.db")


def init_db(db_path: str) -> None:
    """Initialize SQLite database with trades table."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            entry REAL NOT NULL,
            exit REAL,
            result TEXT,
            score INTEGER,
            pnl REAL DEFAULT 0,
            pnl_pct REAL DEFAULT 0,
            duration_bars INTEGER DEFAULT 0,
            rationale TEXT
        )
    """)
    conn.commit()
    conn.close()


def calculate_pnl(entry: float, exit_price: float, position_size: float = 1.0) -> tuple[float, float]:
    """Calculate PnL for a long position."""
    pnl = (exit_price - entry) * position_size
    pnl_pct = ((exit_price / entry) - 1) * 100 if entry > 0 else 0
    return round(pnl, 2), round(pnl_pct, 2)


def record_trade(
    db_path: str,
    trade_date: str,
    symbol: str,
    entry_price: float,
    exit_price: float | None,
    score: int,
    rationale: str = "",
    position_size: float = 1.0,
) -> dict:
    """Record a single trade to the database."""
    init_db(db_path)

    if exit_price is not None and entry_price > 0:
        pnl, pnl_pct = calculate_pnl(entry_price, exit_price, position_size)
        result = "WIN" if pnl > 0 else ("LOSS" if pnl < 0 else "BREAKEVEN")
    else:
        pnl = 0.0
        pnl_pct = 0.0
        result = "OPEN"

    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        """INSERT INTO trades (date, symbol, entry, exit, result, score, pnl, pnl_pct, rationale)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (trade_date, symbol, entry_price, exit_price, result, score, pnl, pnl_pct, rationale),
    )
    conn.commit()
    conn.close()

    return {
        "symbol": symbol,
        "date": trade_date,
        "entry": entry_price,
        "exit": exit_price,
        "result": result,
        "pnl": pnl,
        "pnl_pct": pnl_pct,
    }


def generate_eod_report(db_path: str, report_date: str | None = None) -> dict:
    """Generate end-of-day performance report from trade database."""
    init_db(db_path)

    if report_date is None:
        report_date = date_type.today().isoformat()

    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT * FROM trades WHERE date = ? ORDER BY symbol", (report_date,)
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {
            "date": report_date,
            "no_trades": True,
            "message": f"No trades recorded for {report_date}. NO TRADE DAY confirmed.",
        }

    # Column order (SELECT *): id=0, date=1, symbol=2, entry=3, exit=4,
    # result=5, score=6, pnl=7, pnl_pct=8, duration_bars=9, rationale=10
    wins = [r for r in rows if r[5] == "WIN"]
    losses = [r for r in rows if r[5] == "LOSS"]
    open_positions = [r for r in rows if r[5] == "OPEN"]

    total_pnl = sum(r[8] for r in rows)  # pnl_pct column
    avg_win = (sum(r[8] for r in wins) / len(wins)) if wins else 0
    avg_loss = (sum(r[8] for r in losses) / len(losses)) if losses else 0

    report = {
        "date": report_date,
        "no_trades": False,
        "total_trades": len(rows),
        "wins": len(wins),
        "losses": len(losses),
        "open_positions": len(open_positions),
        "win_rate": round(len(wins) / max(1, len([r for r in rows if r[5] != "OPEN"])) * 100, 1),
        "total_pnl_pct": round(total_pnl, 2),
        "avg_win_pct": round(avg_win, 2),
        "avg_loss_pct": round(abs(avg_loss), 2) if losses else 0,
        "trades": [
            {
                "symbol": r[2],
                "entry": r[3],
                "exit": r[4],
                "result": r[5],
                "pnl_pct": r[8],
                "score": r[6],
            }
            for r in rows
        ],
    }

    if open_positions:
        report["open_positions_detail"] = [
            {"symbol": r[2], "entry": r[3]} for r in open_positions
        ]

    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="End-of-Day module for BIST AI Trader v1.0.")
    ap.add_argument("--db", default=DB_PATH, help="SQLite database path")
    ap.add_argument("--date", default=None, help="Report date (default: today)")
    ap.add_argument("--record", action="store_true", help="Record a new trade from stdin")
    ap.add_argument("--output", "-o", default=None, help="Output JSON file for report")
    args = ap.parse_args()

    init_db(args.db)

    if args.record:
        try:
            data = json.load(sys.stdin)
        except Exception as e:
            print(f"[ERROR] Failed to parse stdin JSON: {e}", file=sys.stderr)
            return 1

        result = record_trade(
            db_path=args.db,
            trade_date=data.get("date", ""),
            symbol=data.get("symbol", "UNKNOWN"),
            entry_price=float(data.get("entry", 0)),
            exit_price=float(data["exit"]) if data.get("exit") is not None else None,
            score=int(data.get("score", 0)),
            rationale=data.get("rationale", ""),
        )
        print(json.dumps(result, indent=2))
    else:
        report = generate_eod_report(args.db, args.date)

        if args.output:
            with open(args.output, "w") as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
            print(f"[OK] EOD report saved to {args.output}", file=sys.stderr)
        else:
            print(json.dumps(report, indent=2, ensure_ascii=False))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
