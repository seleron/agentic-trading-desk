#!/usr/bin/env python3
"""
validation_tracker.py
=====================
Daily validation/backtesting tracker for scoring engine accuracy.

Tracks morning score predictions against actual end-of-day prices,
computes deltas, and generates periodic accuracy reports.

Usage:
    # Record a morning snapshot
    python3 scripts/validation_tracker.py --mode morning --date 2026-07-11 \
        --symbol EREGL --score 75 --decision BUY ...

    # Record end-of-day actuals
    python3 scripts/validation_tracker.py --mode eod --date 2026-07-11 \
        --symbols EREGL ASELS THYAO SISE ANHYT

    # Generate a validation report
    python3 scripts/validation_tracker.py --mode report \
        --start 2026-07-01 --end 2026-07-11

Database: SQLite at data/validation.db (local backup).
Google Sheets: Optional — writes to "Agentic Trading Validation" sheet.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
import time
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS = ["EREGL", "ASELS", "THYAO", "SISE", "ANHYT"]

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "validation.db")

GOOGLE_SHEET_TITLE = "Agentic Trading Validation"

# Google Sheets fallback: use this key if no credentials available.
# A real deployment would use service account JSON or OAuth2 tokens.
GOOGLE_SHEETS_API_KEY = os.environ.get("GOOGLE_SHEETS_API_KEY", "")


def _is_trading_day(d: date) -> bool:
    """Return True if *d* is a weekday (Mon–Fri).

    BIST holidays are not checked — the caller should skip them, or this can
    be extended with a Turkish holiday list.  Weekends are always skipped.
    """
    return d.weekday() < 5


def _get_morning_closes(
    symbols: list[str], target_date: str
) -> dict[str, dict]:
    """Fetch morning snapshot prices via yfinance for BIST tickers.

    Returns a dict mapping symbol → {close, high, low, open, volume, timestamp}
    using the last available daily candle before market open (~10:30 TRT).

    Args:
        symbols: List of BIST ticker symbols (e.g., "EREGL", "THYAO").
        target_date: Date string in YYYY-MM-DD format.

    Returns:
        Dict of symbol → price dict, or empty dict on failure.
    """
    import yfinance as yf

    result = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(f"{sym}.IS")
            hist = ticker.history(period="5d", auto_adjust=True)
            if hist.empty:
                logger.warning("No history for %s.IS — skipping", sym)
                continue

            # Get the last available row (most recent data point)
            latest = hist.iloc[-1]
            result[sym] = {
                "close": float(latest["Close"]),
                "open": float(latest["Open"]),
                "high": float(latest["High"]),
                "low": float(latest["Low"]),
                "volume": int(latest["Volume"]) if not math.isnan(latest["Volume"]) else 0,
                "timestamp": hist.index[-1].isoformat(),
            }
        except Exception as exc:
            logger.warning("Failed to fetch morning data for %s.IS: %s", sym, exc)

    return result


def _get_eod_closes(
    symbols: list[str], target_date: str
) -> dict[str, dict]:
    """Fetch end-of-day closing prices via yfinance.

    Uses the same daily candle as morning (market closes at 17:30 TRT).

    Args:
        symbols: List of BIST ticker symbols.
        target_date: Date string in YYYY-MM-DD format.

    Returns:
        Dict mapping symbol → {close, high, low, open, volume}.
    """
    return _get_morning_closes(symbols, target_date)


def _fetch_score_for_symbol(
    symbol: str, date_str: str, db_path: str
) -> Optional[dict]:
    """Load a morning snapshot for *symbol* on *date_str* from SQLite.

    Args:
        symbol: BIST ticker.
        date_str: Date in YYYY-MM-DD format.
        db_path: Path to the validation.db database.

    Returns:
        Dict with score data, or None if not found.
    """
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT * FROM morning_snapshots WHERE date = ? AND symbol = ?",
        (date_str, symbol),
    )
    row = cursor.fetchone()
    conn.close()

    if row is None:
        return None

    columns = [desc[0] for desc in cursor.description]
    return dict(zip(columns, row))


# ---------------------------------------------------------------------------
# SQLite backend
# ---------------------------------------------------------------------------


def init_db(db_path: str) -> sqlite3.Connection:
    """Initialize the validation database with required tables."""
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS morning_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            score REAL,
            decision TEXT,
            rsi REAL,
            macd REAL,
            ema20 REAL,
            ema50 REAL,
            ema200 REAL,
            close_price REAL,
            rationale TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS eod_actuals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            symbol TEXT NOT NULL,
            morning_close REAL,
            open_price REAL,
            high REAL,
            low REAL,
            close_price REAL,
            volume REAL,
            delta_pct REAL,
            prediction_correct INTEGER,  -- 1 = correct, 0 = incorrect
            accuracy_flag TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS weekly_summaries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            week_start TEXT NOT NULL,
            week_end TEXT NOT NULL,
            total_predictions INTEGER,
            correct_predictions INTEGER,
            accuracy_pct REAL,
            avg_delta_correct REAL,
            avg_delta_incorrect REAL,
            symbol_accuracy TEXT,  -- JSON-encoded dict of symbol → accuracy pct
            created_at TEXT DEFAULT (datetime('now'))
        )
    """)

    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_snapshots_date_symbol
            ON morning_snapshots(date, symbol)
    """)
    conn.execute("""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_eod_date_symbol
            ON eod_actuals(date, symbol)
    """)

    conn.commit()
    return conn


def record_morning_score(
    date_str: str,
    symbols_data: dict[str, dict],
    db_path: Optional[str] = None,
) -> list[dict]:
    """Record morning snapshot scores for a batch of symbols.

    Args:
        date_str: Date in YYYY-MM-DD format.
        symbols_data: Dict mapping symbol → {score, decision, rsi, macd, ema20,
                      ema50, ema200, close_price, rationale}.
        db_path: Database path (default: DB_PATH constant).

    Returns:
        List of inserted record dicts.
    """
    if db_path is None:
        db_path = DB_PATH
    conn = init_db(db_path)

    records = []
    for sym, data in symbols_data.items():
        try:
            conn.execute(
                """INSERT OR REPLACE INTO morning_snapshots
                   (date, symbol, score, decision, rsi, macd, ema20, ema50, ema200, close_price, rationale)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    date_str,
                    sym,
                    data.get("score"),
                    data.get("decision"),
                    data.get("rsi"),
                    data.get("macd"),
                    data.get("ema20"),
                    data.get("ema50"),
                    data.get("ema200"),
                    data.get("close_price"),
                    json.dumps(data.get("rationale", "")) if isinstance(data.get("rationale"), list) else str(data.get("rationale", "")),
                ),
            )
            records.append({
                "date": date_str,
                "symbol": sym,
                "score": data.get("score"),
                "close_price": data.get("close_price"),
            })
        except Exception as exc:
            logger.error("Failed to record morning snapshot for %s on %s: %s", sym, date_str, exc)

    conn.commit()
    conn.close()
    return records


def record_eod_actuals(
    date_str: str,
    symbols_data: dict[str, dict],
    db_path: Optional[str] = None,
) -> list[dict]:
    """Record end-of-day actual prices and compute deltas.

    For each symbol, looks up the morning snapshot close price (as reference),
    then computes delta_pct = (eod_close - morning_close) / morning_close * 100.

    Prediction correctness:
        score >= 60 AND price went up → CORRECT
        score < 60 AND price went down → CORRECT
        otherwise → INCORRECT

    Args:
        date_str: Date in YYYY-MM-DD format.
        symbols_data: Dict mapping symbol → {close_price, open_price, high, low, volume}.
        db_path: Database path (default: DB_PATH constant).

    Returns:
        List of inserted record dicts with delta and accuracy info.
    """
    if db_path is None:
        db_path = DB_PATH
    conn = init_db(db_path)

    records = []
    for sym, data in symbols_data.items():
        # Look up morning snapshot for this symbol/date
        cursor = conn.execute(
            "SELECT score, close_price FROM morning_snapshots WHERE date = ? AND symbol = ?",
            (date_str, sym),
        )
        row = cursor.fetchone()

        if row is None:
            logger.warning("No morning snapshot found for %s on %s — skipping EOD", sym, date_str)
            continue

        morning_score, morning_close = row[0], row[1]

        eod_close = data.get("close_price")
        if eod_close is None or morning_close is None or morning_close <= 0:
            logger.warning(
                "Insufficient data for %s on %s (eod_close=%s, morning_close=%s) — skipping",
                sym, date_str, eod_close, morning_close,
            )
            continue

        delta_pct = round((eod_close - morning_close) / morning_close * 100, 4)

        # Determine prediction correctness
        if morning_score is not None and morning_score >= 60:
            correct = eod_close > morning_close
        elif morning_score is not None and morning_score < 60:
            correct = eod_close < morning_close
        else:
            # No score available — neutral
            correct = False

        accuracy_flag = "CORRECT" if correct else "INCORRECT"

        try:
            conn.execute(
                """INSERT OR REPLACE INTO eod_actuals
                   (date, symbol, morning_close, open_price, high, low, close_price, volume, delta_pct, prediction_correct, accuracy_flag)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    date_str,
                    sym,
                    round(morning_close, 4),
                    data.get("open_price"),
                    data.get("high"),
                    data.get("low"),
                    round(eod_close, 4),
                    data.get("volume"),
                    delta_pct,
                    1 if correct else 0,
                    accuracy_flag,
                ),
            )
            records.append({
                "date": date_str,
                "symbol": sym,
                "morning_score": morning_score,
                "morning_close": round(morning_close, 4),
                "eod_close": round(eod_close, 4),
                "delta_pct": delta_pct,
                "prediction_correct": correct,
                "accuracy_flag": accuracy_flag,
            })
        except Exception as exc:
            logger.error("Failed to record EOD actuals for %s on %s: %s", sym, date_str, exc)

    conn.commit()
    conn.close()
    return records


def generate_validation_report(
    start_date: str,
    end_date: str,
    db_path: Optional[str] = None,
) -> dict:
    """Generate a validation report aggregating accuracy stats.

    Args:
        start_date: Start date in YYYY-MM-DD format (inclusive).
        end_date: End date in YYYY-MM-DD format (inclusive).
        db_path: Database path (default: DB_PATH constant).

    Returns:
        Dict with summary statistics including overall accuracy, per-symbol stats,
        and delta analysis.
    """
    if db_path is None:
        db_path = DB_PATH
    conn = init_db(db_path)

    cursor = conn.execute(
        """SELECT date, symbol, morning_close, close_price, delta_pct,
                  prediction_correct, accuracy_flag
           FROM eod_actuals
           WHERE date >= ? AND date <= ?
           ORDER BY date, symbol""",
        (start_date, end_date),
    )
    rows = cursor.fetchall()
    conn.close()

    if not rows:
        return {
            "date_range": {"start": start_date, "end": end_date},
            "no_data": True,
            "message": f"No validation data found for {start_date} to {end_date}.",
        }

    total = len(rows)
    correct = sum(1 for r in rows if r[5] == 1)
    accuracy_pct = round(correct / max(1, total) * 100, 2)

    # Per-symbol breakdown — single pass through rows
    symbol_stats: dict[str, dict[str, Any]] = {}
    for row in rows:
        sym = row[1]
        if sym not in symbol_stats:
            symbol_stats[sym] = {"total": 0, "correct": 0}
        symbol_stats[sym]["total"] += 1
        if row[5] == 1:
            symbol_stats[sym]["correct"] += 1

    for sym in symbol_stats:
        stats = symbol_stats[sym]
        stats["accuracy_pct"] = round(stats["correct"] / max(1, stats["total"]) * 100, 2) if stats["total"] > 0 else 0.0

    # Delta analysis
    deltas_correct = [r[4] for r in rows if r[5] == 1]
    deltas_incorrect = [r[4] for r in rows if r[5] == 0]

    avg_delta_correct = round(sum(deltas_correct) / len(deltas_correct), 4) if deltas_correct else None
    avg_delta_incorrect = round(sum(deltas_incorrect) / len(deltas_incorrect), 4) if deltas_incorrect else None

    # Store weekly summary in DB for future reference
    week_start = start_date
    week_end = end_date
    try:
        conn = init_db(db_path)
        symbol_accuracy_json = json.dumps(symbol_stats, default=str)
        conn.execute(
            """INSERT INTO weekly_summaries
               (week_start, week_end, total_predictions, correct_predictions, accuracy_pct, avg_delta_correct, avg_delta_incorrect, symbol_accuracy)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (week_start, week_end, total, correct, accuracy_pct, avg_delta_correct, avg_delta_incorrect, symbol_accuracy_json),
        )
        conn.commit()
        conn.close()
    except Exception as exc:
        logger.warning("Failed to store weekly summary: %s", exc)

    report = {
        "date_range": {"start": start_date, "end": end_date},
        "total_predictions": total,
        "correct_predictions": correct,
        "accuracy_pct": accuracy_pct,
        "avg_delta_correct": avg_delta_correct,
        "avg_delta_incorrect": avg_delta_incorrect,
        "symbol_accuracy": symbol_stats,
    }

    return report


# ---------------------------------------------------------------------------
# Google Sheets integration (optional)
# ---------------------------------------------------------------------------


def _get_google_sheet_id(api_key: str = "") -> Optional[str]:
  """Look up the Google Sheet ID for 'Agentic Trading Validation'.

  Creates the sheet if it doesn't exist. Returns None on failure.

  This is a simplified approach using Sheets API v4 with a single worksheet.
  A production deployment would use service account authentication.
  """
  if not api_key:
      return None

  # Check for existing sheet ID in environment, or create one
  sheet_id = os.environ.get("GOOGLE_SHEET_ID", "")
  if sheet_id:
      return sheet_id

  # Create a new spreadsheet via Sheets API
  url = f"https://sheets.googleapis.com/v4/spreadsheets?key={api_key}"
  payload = json.dumps({"properties": {"title": GOOGLE_SHEET_TITLE}}).encode()
  req = urllib.request.Request(url, data=payload, method="POST", headers={"Content-Type": "application/json"})

  try:
      with urllib.request.urlopen(req, timeout=10) as resp:
          result = json.loads(resp.read())
          return result.get("spreadsheetId")
  except Exception as exc:
      logger.warning("Failed to create/find Google Sheet: %s", exc)
      return None


def _append_to_google_sheet(
  sheet_id: str, rows: list[list], api_key: str = ""
) -> bool:
  """Append rows to a Google Sheet.

  Args:
      sheet_id: Google Sheets spreadsheet ID.
      rows: List of row data (each row is a list of values).
      api_key: Google API key for authentication.

  Returns:
      True if successful, False otherwise.
  """
  if not sheet_id or not api_key:
      return False

  url = f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}/values:A1:append?valueInputOption=USER_ENTERED&key={api_key}"
  payload = json.dumps({"values": rows}).encode()
  req = urllib.request.Request(
      url, data=payload, method="POST", headers={"Content-Type": "application/json"}
  )

  try:
      with urllib.request.urlopen(req, timeout=10) as resp:
          return resp.status == 200
  except Exception as exc:
      logger.warning("Failed to append to Google Sheet: %s", exc)
      return False


def write_to_google_sheets(
    records: list[dict],
    mode: str = "morning",
    api_key: str = "",
) -> bool:
    """Write validation records to Google Sheets with SQLite fallback.

    Args:
        records: List of record dicts from record_morning_score or record_eod_actuals.
        mode: Either 'morning' or 'eod'.
        api_key: Google API key (default: GOOGLE_SHEETS_API_KEY env var).

    Returns:
        True if write succeeded, False otherwise (but data is still in SQLite).
    """
    sheet_id = _get_google_sheet_id(api_key)
    if not sheet_id:
        logger.info("No Google Sheet available — records stored in SQLite only")
        return False

    if mode == "morning":
        header = ["Date", "Symbol", "Score", "Decision", "RSI", "MACD",
                  "EMA20", "EMA50", "EMA200", "Morning_Close"]
        rows = []
        for r in records:
            rows.append([
                r.get("date"),
                r.get("symbol"),
                r.get("score"),
                r.get("decision"),
                r.get("rsi"),
                r.get("macd"),
                r.get("ema20"),
                r.get("ema50"),
                r.get("ema200"),
                r.get("close_price"),
            ])
    else:  # eod
        header = ["Date", "Symbol", "Morning_Close", "EOD_Close",
                  "Delta_Pct", "Prediction_Correct", "Accuracy_Flag"]
        rows = []
        for r in records:
            rows.append([
                r.get("date"),
                r.get("symbol"),
                r.get("morning_close"),
                r.get("eod_close"),
                r.get("delta_pct"),
                r.get("prediction_correct"),
                r.get("accuracy_flag"),
            ])

    # Prepend header if first write (check via append)
    full_rows = [header] + rows if rows else []

    success = _append_to_google_sheet(sheet_id, full_rows, api_key)
    return success


# ---------------------------------------------------------------------------
# Scoring engine integration: prepare morning snapshot from score_quote output
# ---------------------------------------------------------------------------


def prepare_morning_snapshot(
    date_str: str,
    scored_quotes: list[dict],
    db_path: Optional[str] = None,
) -> list[dict]:
    """Convert scoring_engine outputs into validation tracker records.

    Takes the output of score_quote() or score_quotes() and converts each
    result into a morning_snapshot-ready dict.

    Args:
        date_str: Date in YYYY-MM-DD format.
        scored_quotes: List of dicts from score_quote()/score_quotes() calls,
                       each containing 'score', 'raw_components', 'rationale'.
        db_path: Database path (default: DB_PATH constant).

    Returns:
        List of record dicts suitable for record_morning_score().
    """
    symbols_data = {}
    for sq in scored_quotes:
        sym = sq.get("symbol", "UNKNOWN")
        raw = sq.get("raw_components", {})
        rationale = sq.get("rationale", [])

        # Extract key indicators from the scoring result
        decision = "BUY" if sq.get("score", 0) >= 60 else ("SELL" if sq.get("score", 0) < 40 else "HOLD")

        symbols_data[sym] = {
            "score": sq.get("score"),
            "decision": decision,
            "rsi": None,  # Would need to be passed through from indicators
            "macd": raw.get("momentum", 0),
            "ema20": None,  # Needs indicator data
            "ema50": None,
            "ema200": None,
            "close_price": None,  # Set by caller via _get_morning_closes
            "rationale": rationale,
        }

    records = record_morning_score(date_str, symbols_data, db_path)

    # Update close prices from morning data
    if records:
        symbol_list = list(symbols_data.keys())
        morning_prices = _get_morning_closes(symbol_list, date_str)
        for sym, price_data in morning_prices.items():
            if sym in symbols_data:
                symbols_data[sym]["close_price"] = price_data["close"]

        # Re-record with close prices
        record_morning_score(date_str, symbols_data, db_path)

    return records


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Daily validation tracker for scoring engine accuracy."
    )
    ap.add_argument(
        "--mode", "-m", required=True,
        choices=["morning", "eod", "report"],
        help="Operation mode.",
    )
    ap.add_argument("--date", "-d", default=None, help="Date (YYYY-MM-DD).")
    ap.add_argument("--symbols", nargs="+", default=None, help="Symbols to process.")
    ap.add_argument(
        "--score", type=float, default=None, help="Score value (morning mode)."
    )
    ap.add_argument(
        "--decision", default=None, help='Decision string: BUY/SELL/HOLD.'
    )
    ap.add_argument("--rsi", type=float, default=None, help="RSI value.")
    ap.add_argument("--macd", type=float, default=None, help="MACD value.")
    ap.add_argument("--ema20", type=float, default=None, help="EMA 20 value.")
    ap.add_argument("--ema50", type=float, default=None, help="EMA 50 value.")
    ap.add_argument("--ema200", type=float, default=None, help="EMA 200 value.")
    ap.add_argument(
        "--start", default=None, help="Report start date (YYYY-MM-DD)."
    )
    ap.add_argument(
        "--end", default=None, help="Report end date (YYYY-MM-DD)."
    )
    ap.add_argument("--db", default=DB_PATH, help="SQLite database path.")
    ap.add_argument("--api-key", default=GOOGLE_SHEETS_API_KEY, help="Google Sheets API key.")

    args = ap.parse_args()

    if args.mode == "morning":
        if not args.date:
            print("[ERROR] --date required for morning mode.", file=sys.stderr)
            return 1

        today_str = args.date
        symbols = args.symbols or DEFAULT_SYMBOLS

        # Fetch morning prices via yfinance
        morning_prices = _get_morning_closes(symbols, today_str)

        if not morning_prices:
            print(f"[WARN] No morning data fetched for {symbols} on {today_str}", file=sys.stderr)

        # Prepare scored quotes from scoring engine (simplified — uses CLI args or defaults)
        scored_quotes = []
        for sym in symbols:
            price_data = morning_prices.get(sym, {})
            close_price = price_data.get("close")
            if close_price is None and args.score is not None:
                # Use provided score without yfinance data
                scored_quotes.append({
                    "symbol": sym,
                    "score": args.score or 50.0,
                    "raw_components": {
                        "momentum": args.macd if args.macd else 0,
                    },
                    "rationale": [f"Score: {args.score}", f"Decision: {args.decision}"],
                })
            elif close_price is not None:
                # Simulated score for testing — in production this comes from scoring_engine.py
                simulated_score = 50.0 + (close_price % 10) * 2  # deterministic pseudo-score
                scored_quotes.append({
                    "symbol": sym,
                    "score": simulated_score,
                    "raw_components": {
                        "momentum": args.macd if args.macd else 0,
                    },
                    "rationale": [f"Simulated score based on close={close_price}"],
                })

        records = prepare_morning_snapshot(today_str, scored_quotes, args.db)

        print(json.dumps(records, indent=2))
        return 0

    elif args.mode == "eod":
        if not args.date:
            print("[ERROR] --date required for EOD mode.", file=sys.stderr)
            return 1

        symbols = args.symbols or DEFAULT_SYMBOLS
        eod_prices = _get_eod_closes(symbols, args.date)

        if not eod_prices:
            # Use CLI-provided close prices as fallback
            if args.score is not None and args.decision:
                eod_data = {}
                for sym in symbols:
                    eod_data[sym] = {
                        "close_price": float(args.score),
                        "open_price": float(args.score) * 0.98,
                        "high": float(args.score) * 1.02,
                        "low": float(args.score) * 0.97,
                    }
                records = record_eod_actuals(args.date, eod_data, args.db)
            else:
                print(f"[WARN] No EOD data for {symbols} on {args.date}", file=sys.stderr)
                return 1

        print(json.dumps(records, indent=2))
        return 0

    elif args.mode == "report":
        if not args.start or not args.end:
            print("[ERROR] --start and --end required for report mode.", file=sys.stderr)
            return 1

        report = generate_validation_report(args.start, args.end, args.db)
        print(json.dumps(report, indent=2))
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
