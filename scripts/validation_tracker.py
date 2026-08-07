#!/usr/bin/env python3
"""
validation_tracker.py
=====================
Daily validation tracker for scoring engine accuracy (forward-only).

Tracks morning score predictions against actual end-of-day prices,
computes deltas, and generates periodic accuracy reports.

Forward-only constraint: All date inputs are hard-guarded to today's date.
Historical dates raise ValueError — this module cannot backtest past data
because yfinance does not support absolute date-range queries (only relative
periods like "5d", "1mo"), so recording prices under a historical date would
silently store today's values with the wrong date label.

Usage:
    # Record a morning snapshot (date must be today)
    python3 scripts/validation_tracker.py --mode morning --date 2026-07-11 \
        --symbol EREGL --score 75 --decision BUY ...

    # Record end-of-day actuals
    python3 scripts/validation_tracker.py --mode eod --date 2026-07-11 \
        --symbols EREGL ASELS THYAO SISE ANHYT

    # Generate a validation report (report CAN cover historical ranges)
    python3 scripts/validation_tracker.py --mode report \
        --start 2026-07-01 --end 2026-07-11

    # Morning snapshot from pipeline output (preferred — avoids re-scoring):
    python3 scripts/validation_tracker.py --mode morning --date 2026-07-11 \
        --scores-file outputs/scores.json --symbols EREGL ASELS THYAO SISE ANHYT

Database: SQLite at data/validation.db (local backup).
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sqlite3
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration defaults
# ---------------------------------------------------------------------------

DEFAULT_SYMBOLS = ["EREGL", "ASELS", "THYAO", "SISE", "ANHYT"]

DB_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "validation.db")


def _is_trading_day(d: date) -> bool:
    """Return True if *d* is a weekday (Mon–Fri).

    BIST holidays are not checked — the caller should skip them, or this can
    be extended with a Turkish holiday list.  Weekends are always skipped.
    """
    return d.weekday() < 5


def _get_morning_closes(
    symbols: list[str], target_date: str, use_long_history: bool = False
) -> dict[str, dict]:
    """Fetch morning snapshot prices via yfinance for BIST tickers.

    Uses the **prior trading day's close** as the reference price so that EOD
    delta computation (close − morning_close) / morning_close yields a genuine
    intraday movement rather than always zero.  When only one bar is available,
    falls back to that bar.

    Args:
        symbols: List of BIST ticker symbols (e.g., "EREGL", "THYAO").
        target_date: Date string in YYYY-MM-DD format — must be today's date,
            otherwise a ValueError is raised to prevent recording stale prices
            under a historical date.
        use_long_history: When True, fetches up to 1 month of history so that
            technical indicators (RSI-14, EMA-20) have enough data points for
            meaningful computation by the scoring engine.

    Returns:
        Dict of symbol → price dict with optional '_history_closes' key when
        use_long_history=True.  The 'close' field is the **prior trading day's**
        close; all other OHLCV fields come from the same bar for context.

    Raises:
        ValueError: If *target_date* is not today's date.
    """
    # Hard-guard: reject non-today dates to prevent backtest misuse that would
    # silently record today's prices under a historical date (yfinance only
    # supports relative period queries, not absolute date ranges).
    try:
        requested = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid target_date format: {target_date!r} — expected YYYY-MM-DD")
    if requested != date.today():
        raise ValueError(
            f"target_date must be today ({date.today().isoformat()}), got {requested.isoformat()}. "
            "yfinance does not support absolute date-range queries, so historical dates would "
            "silently record today's prices under the wrong date."
        )

    import yfinance as yf

    period = "1mo" if use_long_history else "5d"
    result = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(f"{sym}.IS")
            hist = ticker.history(period=period, auto_adjust=True)
            if hist.empty:
                logger.warning("No history for %s.IS — skipping", sym)
                continue

            # Use the *prior* trading day's candle as the morning reference so
            # that EOD delta (today_close − prior_close) / prior_close is
            # genuinely non-zero when markets move.  Fall back to the last bar
            # if there is only one row of data.
            ref_idx = -2 if len(hist) >= 2 else -1
            ref = hist.iloc[ref_idx]

            entry = {
                "close": float(ref["Close"]),
                "open": float(ref["Open"]),
                "high": float(ref["High"]),
                "low": float(ref["Low"]),
                "volume": int(ref["Volume"]) if not math.isnan(ref["Volume"]) else 0,
                "timestamp": hist.index[ref_idx].isoformat(),
            }

            # Include full historical closes for indicator computation
            if use_long_history:
                entry["_history_closes"] = [float(v) for v in hist["Close"].tolist()]

            result[sym] = entry
        except Exception as exc:
            logger.warning("Failed to fetch morning data for %s.IS: %s", sym, exc)

    return result


def _get_eod_closes(
    symbols: list[str], target_date: str
) -> dict[str, dict]:
    """Fetch end-of-day closing prices via yfinance.

    Uses the most recent available daily candle (today's actual close at
    market close 17:30 TRT).  This is deliberately different from morning mode
    which uses the prior trading day's close — so delta computation between
    the two modes is meaningful.

    Args:
        symbols: List of BIST ticker symbols.
        target_date: Date string in YYYY-MM-DD format — must be today's date,
            otherwise a ValueError is raised (same constraint as _get_morning_closes).

    Returns:
        Dict mapping symbol → {close, high, low, open, volume}.

    Raises:
        ValueError: If *target_date* is not today's date.
    """
    # Hard-guard: same constraint as _get_morning_closes — reject non-today dates.
    try:
        requested = datetime.strptime(target_date, "%Y-%m-%d").date()
    except ValueError:
        raise ValueError(f"Invalid target_date format: {target_date!r} — expected YYYY-MM-DD")
    if requested != date.today():
        raise ValueError(
            f"target_date must be today ({date.today().isoformat()}), got {requested.isoformat()}. "
            "yfinance does not support absolute date-range queries."
        )

    import yfinance as yf

    result = {}
    for sym in symbols:
        try:
            ticker = yf.Ticker(f"{sym}.IS")
            hist = ticker.history(period="5d", auto_adjust=True)
            if hist.empty:
                logger.warning("No history for %s.IS — skipping", sym)
                continue

            # EOD uses the last available row — today's actual closing price.
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
            logger.warning("Failed to fetch EOD data for %s.IS: %s", sym, exc)

    return result


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

    Prediction correctness per engine decision bands:
        BUY  (score >= 60) → expects UP   → correct if eod_close > morning_close
        SELL (score < 40)  → expects DOWN → correct if eod_close < morning_close
        HOLD (40 <= score < 60) → no directionality → recorded with NEUTRAL flag,
            excluded from prediction-correctness counting.

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

        # Determine prediction correctness per engine decision bands
        if morning_score is not None and morning_score >= 60:
            # BUY signal — expects price to go up
            correct = eod_close > morning_close
            accuracy_flag = "CORRECT" if correct else "INCORRECT"
        elif morning_score is not None and morning_score < 40:
            # SELL signal — expects price to go down
            correct = eod_close < morning_close
            accuracy_flag = "CORRECT" if correct else "INCORRECT"
        else:
            # HOLD (40 <= score < 60) or no score — no directional expectation
            correct = None  # excluded from prediction-correctness counting
            accuracy_flag = "NEUTRAL"

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

    # Separate directional predictions from NEUTRAL (HOLD) signals.
    # NEUTRAL rows have accuracy_flag='NEUTRAL' and are excluded from accuracy stats.
    directional = [r for r in rows if r[6] != "NEUTRAL"]  # r[6] = accuracy_flag

    total = len(directional)
    correct = sum(1 for r in directional if r[5] == 1)  # r[5] = prediction_correct
    accuracy_pct = round(correct / max(1, total) * 100, 2)

    # Per-symbol breakdown — single pass through rows (directional only).
    symbol_stats: dict[str, dict[str, Any]] = {}
    for row in directional:
        sym = row[1]
        if sym not in symbol_stats:
            symbol_stats[sym] = {"total": 0, "correct": 0}
        symbol_stats[sym]["total"] += 1
        if row[5] == 1:
            symbol_stats[sym]["correct"] += 1

    for sym in symbol_stats:
        stats = symbol_stats[sym]
        stats["accuracy_pct"] = round(stats["correct"] / max(1, stats["total"]) * 100, 2) if stats["total"] > 0 else 0.0

    # Delta analysis (directional only).
    deltas_correct = [r[4] for r in directional if r[5] == 1]
    deltas_incorrect = [r[4] for r in directional if r[5] == 0]

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
# Scoring engine integration: prepare morning snapshot from score_quote output
# ---------------------------------------------------------------------------


def load_scores_from_file(scores_path: str) -> list[dict]:
    """Load scored quotes from a pipeline output JSON file.

    Reads ``outputs/scores.json`` (or any JSON file with the same format as
    :func:`scoring_engine.score_quotes` output) and returns the list of scored
    quote dicts ready for :func:`prepare_morning_snapshot`.

    The expected format is a JSON array where each element has at least::

        {"symbol": ..., "score": ..., "raw_components": {...}, "rationale": [...]}

    Args:
        scores_path: Path to the scores/selection JSON file.

    Returns:
        List of scored-quote dicts (each with ``symbol``, ``score``,
        ``raw_components``, and ``rationale`` keys).

    Raises:
        FileNotFoundError: If *scores_path* does not exist.
        ValueError: If the file is not valid JSON or contains an unexpected structure.
    """
    import json as _json

    with open(scores_path) as f:
        data = _json.load(f)

    # The orchestrator writes scores.json as a plain list of scored quotes,
    # while scoring_engine.py's CLI writes {"scores": [...], "selection": {...}}.
    if isinstance(data, dict):
        if "scores" in data:
            return data["scores"]  # scoring_engine CLI format
        elif "top_picks" in data:
            # selection.json — extract top picks as scored quotes
            picks = data.get("top_picks", [])
            # Each pick already has symbol/score/raw_components/rationale from select_top_picks
            return picks
    if isinstance(data, list):
        return data

    raise ValueError(f"Unexpected scores file structure (expected list or dict with 'scores'/'top_picks'): {type(data).__name__}")


def prepare_morning_snapshot(
    date_str: str,
    scored_quotes: list[dict],
    close_prices: Optional[dict[str, float]] = None,
    db_path: Optional[str] = None,
) -> list[dict]:
    """Convert scoring_engine outputs into validation tracker records.

    Takes the output of score_quote() or score_quotes() and converts each
    result into a morning_snapshot-ready dict.  If *close_prices* is provided
    (e.g. from an earlier yfinance fetch), those values are used directly;
    otherwise :func:`_get_morning_closes` is called as a fallback to obtain
    current close prices for the symbols.

    Args:
        date_str: Date in YYYY-MM-DD format.
        scored_quotes: List of dicts from score_quote()/score_quotes() calls,
                       each containing 'symbol', 'score', 'raw_components', 'rationale'.
        close_prices: Optional dict mapping symbol → close_price to avoid a
                      redundant yfinance fetch.  When omitted the function
                      falls back to calling :func:`_get_morning_closes`.
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
            "close_price": close_prices.get(sym) if close_prices else None,
            "rationale": rationale,
        }

    records = record_morning_score(date_str, symbols_data, db_path)

    # If no close prices were provided via parameter, fetch them now (single call).
    if close_prices is None and records:
        symbol_list = list(symbols_data.keys())
        morning_prices = _get_morning_closes(symbol_list, date_str)
        for sym, price_data in morning_prices.items():
            if sym in symbols_data:
                symbols_data[sym]["close_price"] = price_data["close"]

        # Re-record with close prices (INSERT OR REPLACE on unique index).
        record_morning_score(date_str, symbols_data, db_path)

    return records


# ---------------------------------------------------------------------------
# Technical indicator helpers for scoring_engine integration
# ---------------------------------------------------------------------------


def _compute_ema(prices: list[float], period: int) -> list[float]:
    """Compute Exponential Moving Average.

    Args:
        prices: List of closing prices (oldest first).
        period: EMA lookback period.

    Returns:
        List of EMA values aligned with input prices (first period-1 entries are None-equivalent).
    """
    if len(prices) < period or period <= 0:
        return []
    multiplier = 2.0 / (period + 1)
    ema = [sum(prices[:period]) / period]
    for price in prices[period:]:
        ema.append((price - ema[-1]) * multiplier + ema[-1])
    # Pad leading values with None-equivalent (we handle this downstream)
    return [None] * (period - 1) + ema


def _compute_rsi(prices: list[float], period: int = 14) -> Optional[float]:
    """Compute RSI-14 using Wilder's smoothing.

    Args:
        prices: List of closing prices (oldest first).
        period: Lookback period (default: 14 per spec).

    Returns:
        RSI value or None if insufficient data.
    """
    if len(prices) < period + 1:
        return None
    deltas = [prices[i] - prices[i - 1] for i in range(1, len(prices))]
    gains = [d if d > 0 else 0 for d in deltas[-period:]]
    losses = [-d if d < 0 else 0 for d in deltas[-period:]]
    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return round(100.0 - (100.0 / (1.0 + rs)), 2)


def _compute_macd(prices: list[float]) -> tuple[Optional[float], Optional[float]]:
    """Compute MACD line and signal line (12, 26, 9).

    Args:
        prices: List of closing prices (oldest first).

    Returns:
        (macd_line, macd_signal) or (None, None) if insufficient data.
    """
    ema_12 = _compute_ema(prices, 12)
    ema_26 = _compute_ema(prices, 26)

    # Align on the longer period (26), compute MACD line
    min_len = len(ema_12) - 25  # after leading Nones from EMA-12
    macd_line_values = []
    for i in range(max(len(ema_12) - len(ema_26), 0), len(ema_12)):
        e12 = ema_12[i] if ema_12[i] is not None else prices[i]
        idx = i - (len(ema_12) - len(ema_26))
        e26 = ema_26[idx] if idx < len(ema_26) and ema_26[idx] is not None else prices[max(i - 25, 0)]
        macd_line_values.append(e12 - e26)

    if len(macd_line_values) < 9:
        return None, None

    signal = _compute_ema(macd_line_values, 9)
    if not signal or signal[-1] is None:
        return round(macd_line_values[-1], 4), None
    return round(macd_line_values[-1], 4), round(signal[-1], 4)


def _score_with_engine(
    symbol: str, close_price: float, open_price: float, high: float, low: float, volume: int, history: list[float]
) -> dict:
    """Score a single quote using scoring_engine.py.

    Computes technical indicators from the price history and passes them to
    score_quote() so validation measures the real engine's output, not a stub.

    Args:
        symbol: BIST ticker symbol (e.g., "EREGL").
        close_price: Current closing price.
        open_price: Opening price of the candle.
        high: High of the candle.
        low: Low of the candle.
        volume: Trading volume.
        history: List of historical closing prices (oldest first), used to compute indicators.

    Returns:
        Dict with 'score', 'raw_components', and 'rationale' keys suitable for
        prepare_morning_snapshot().
    """
    # Compute technical indicators from available price history
    rsi = _compute_rsi(history, 14)
    ema20_vals = _compute_ema(history, 20)
    ema50_vals = _compute_ema(history, 50)
    ema200_vals = _compute_ema(history, 200)

    # Get the latest EMA values (last non-None entry)
    def _latest(vals: list[float]) -> Optional[float]:
        for v in reversed(vals):
            if v is not None:
                return round(v, 4)
        return None

    ema20 = _latest(ema20_vals)
    ema50 = _latest(ema50_vals)
    ema200 = _latest(ema200_vals)

    macd_val, macd_signal = _compute_macd(history)

    # Build the quote dict in scoring_engine's expected format
    from scoring_engine import score_quote

    quote = {
        "symbol": symbol,
        "close": close_price,
        "open": open_price,
        "high": high,
        "low": low,
        "volume": float(volume),
        "rsi": rsi,
        "macd": macd_val if macd_val is not None else 0.0,
        "macd_signal": macd_signal if macd_signal is not None else 0.0,
        "ema20": ema20,
        "ema50": ema50,
        "ema200": ema200,
    }

    result = score_quote(quote)
    return {
        "score": result["score"],
        "raw_components": result["raw_components"],
        "rationale": result["rationale"],
    }


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
    ap.add_argument(
        "--scores-file", default=None,
        help="Path to pipeline output JSON (outputs/scores.json or selection.json). "
             "When provided, morning scores are loaded from the file instead of "
             "being recomputed via yfinance + scoring_engine.",
    )

    args = ap.parse_args()

    if args.mode == "morning":
        if not args.date:
            print("[ERROR] --date required for morning mode.", file=sys.stderr)
            return 1

        today_str = args.date
        symbols = args.symbols or DEFAULT_SYMBOLS

        # Load scored quotes — either from pipeline output (preferred) or via yfinance + scoring_engine.
        if args.scores_file:
            # Fix #1: ingest actual pipeline output instead of re-scoring.
            print(f"[INFO] Loading scores from {args.scores_file}", file=sys.stderr)
            scored_quotes = load_scores_from_file(args.scores_file)

            # Fetch close prices once (needed for delta computation in EOD).
            morning_prices = _get_morning_closes(symbols, today_str)
            close_price_map = {sym: data["close"] for sym, data in morning_prices.items()}

            records = prepare_morning_snapshot(today_str, scored_quotes, close_prices=close_price_map, db_path=args.db)

        else:
            # Fetch morning prices via yfinance (use 1mo for indicator history).
            morning_prices = _get_morning_closes(symbols, today_str, use_long_history=True)

            if not morning_prices:
                print(f"[WARN] No morning data fetched for {symbols} on {today_str}", file=sys.stderr)

            # Build scored quotes using the real scoring engine when price data is available.
            close_price_map = {}
            scored_quotes = []
            for sym in symbols:
                price_data = morning_prices.get(sym, {})
                close_price = price_data.get("close")
                if close_price is not None:
                    close_price_map[sym] = close_price

                if close_price is None and args.score is not None:
                    # Use provided score without yfinance data (manual CLI input).
                    scored_quotes.append({
                        "symbol": sym,
                        "score": args.score or 50.0,
                        "raw_components": {
                            "momentum": args.macd if args.macd else 0,
                        },
                        "rationale": [f"Score: {args.score}", f"Decision: {args.decision}"],
                    })
                elif close_price is not None:
                    # Real scoring engine integration — compute indicators from history.
                    open_p = price_data.get("open", close_price)
                    high_p = price_data.get("high", close_price)
                    low_p = price_data.get("low", close_price)
                    volume_p = price_data.get("volume", 0) or 1
                    history = price_data.get("_history_closes", [])

                    try:
                        scored = _score_with_engine(
                            sym, close_price, open_p, high_p, low_p, volume_p, history,
                        )
                    except Exception as exc:
                        logger.warning("Scoring engine failed for %s on %s — using fallback: %s", sym, today_str, exc)
                        scored = {
                            "score": 50.0,
                            "raw_components": {"momentum": 0},
                            "rationale": [f"Engine error ({exc}) — fallback score"],
                        }

                    scored_quotes.append(scored)

            # Fix #4: pass close_prices through to avoid double-fetch in prepare_morning_snapshot.
            records = prepare_morning_snapshot(today_str, scored_quotes, close_prices=close_price_map if close_price_map else None, db_path=args.db)

        print(json.dumps(records, indent=2))
        return 0

    elif args.mode == "eod":
        if not args.date:
            print("[ERROR] --date required for EOD mode.", file=sys.stderr)
            return 1

        symbols = args.symbols or DEFAULT_SYMBOLS
        eod_prices = _get_eod_closes(symbols, args.date)

        if eod_prices:
            # Normal path — yfinance returned real EOD closes.
            records = record_eod_actuals(args.date, eod_prices, args.db)
        elif args.score is not None and args.decision:
            # Fallback — use CLI-provided close prices as synthetic EOD data.
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
