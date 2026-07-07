#!/usr/bin/env python3
"""
admin_corrections.py
====================
Admin correction system for manual overrides in the trading engine.

Override types:
  - force_buy:       Force score to 95+ and decision to BUY regardless of computed score
  - force_sell:      Force score below 20 and decision to SELL regardless of computed score
  - ignore:          Skip ticker entirely from selection (same as hardcoded excludes)
  - custom_weight_modifier: Adjust component weights for this ticker only

Corrections are loaded from config.yaml [admin_corrections] section and/or persisted
to a local SQLite database at ~/.config/agentic-trading-desk/corrections.db.

CLI usage:
    python3 scripts/admin_corrections.py add <symbol> --type force_buy --rationale "..."
    python3 scripts/admin_corrections.py remove <symbol>
    python3 scripts/admin_corrections.py list
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Optional


# ── Default component weights (mirrors scoring_engine) ────────────────────────
DEFAULT_COMPONENT_WEIGHTS = {
    "trend": 22,
    "momentum": 18,
    "volume": 15,
    "ema_structure": 15,
    "pivot_position": 10,
    "volatility": 10,
    "pivot_risk": 5,
    "technical_summary": 5,
}


# ── Database path (persistent corrections store) ──────────────────────────────

_CORRECTIONS_DB = os.path.join(
    os.environ.get("HOME", "/tmp"),
    ".config", "agentic-trading-desk", "corrections.db",
)

_SCHEMA = """\
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    override_type TEXT NOT NULL CHECK(override_type IN ('force_buy', 'force_sell', 'ignore', 'custom_weight_modifier')),
    rationale TEXT DEFAULT '',
    weights_json TEXT DEFAULT '{}',          -- JSON object for custom_weight_modifier
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(symbol)                           -- one active correction per symbol
);

CREATE TABLE IF NOT EXISTS correction_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    correction_id INTEGER REFERENCES corrections(id),
    action TEXT NOT NULL,                    -- 'add', 'update', 'remove'
    details_json TEXT DEFAULT '{}',          -- JSON of what changed
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS scoring_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    date TEXT NOT NULL,
    raw_score REAL,
    adjusted_score REAL,
    override_applied TEXT,                   -- which correction was applied
    final_decision TEXT,                     -- BUY / SELL / HOLD
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_scoring_history_symbol ON scoring_history(symbol);
"""


def _get_db() -> sqlite3.Connection:
    """Open (or create) the corrections database."""
    db_dir = os.path.dirname(_CORRECTIONS_DB)
    if not os.path.isdir(db_dir):
        # Non-blocking fallback to /tmp if ~/.config is unwritable
        try:
            os.makedirs(db_dir, exist_ok=True)
        except Exception:
            pass  # in-memory will work as fallback

    conn = sqlite3.connect(_CORRECTIONS_DB)
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _init_db(conn: sqlite3.Connection) -> None:
    """Create tables if they don't exist."""
    for stmt in _SCHEMA.split(";"):
        stmt = stmt.strip()
        if stmt:
            try:
                conn.execute(stmt)
            except Exception:
                pass  # ignore errors from IF NOT EXISTS or duplicate statements


# ── Data classes ──────────────────────────────────────────────────────────────

@dataclass
class AdminCorrection:
    """A single admin correction for a ticker."""
    symbol: str
    override_type: str          # force_buy | force_sell | ignore | custom_weight_modifier
    rationale: str = ""
    weights: dict[str, float] = field(default_factory=dict)  # only for custom_weight_modifier

    def to_dict(self) -> dict:
        return asdict(self)


# ── Core API ──────────────────────────────────────────────────────────────────

def load_corrections_from_config(config: dict) -> dict[str, AdminCorrection]:
    """Load corrections from config.yaml admin_corrections section.

    Returns a dict mapping symbol → AdminCorrection.
    """
    corrections = {}
    ac_section = config.get("admin_corrections", {}) or {}
    if not isinstance(ac_section, dict):
        return corrections

    for symbol, override in ac_section.items():
        if not isinstance(override, dict) or "type" not in override:
            continue
        correction = AdminCorrection(
            symbol=symbol,
            override_type=override.get("type", ""),
            rationale=override.get("rationale", ""),
            weights=override.get("weights", {}),
        )
        corrections[symbol] = correction

    return corrections


def apply_admin_correction(
    score: dict,
    admin_corrections: dict[str, AdminCorrection],
    config: dict,
) -> dict:
    """Apply admin corrections to a single scored quote.

    Modifies the score in-place and returns it for chaining.
    Adds 'admin_override' field describing what was applied (if any).

    Args:
        score: Output from score_quote() — mutated in place.
        admin_corrections: Dict of symbol → AdminCorrection loaded from config.
        config: Full config dict (for fallback weights).

    Returns:
        The modified score dict with 'admin_override' field added.
    """
    symbol = score.get("symbol", "")
    correction = admin_corrections.get(symbol)

    # No correction for this symbol — nothing to do
    if not correction:
        score["admin_override"] = None
        return score

    original_score = score["score"]

    if correction.override_type == "force_buy":
        score["score"] = max(score["score"], 95)
        score["admin_override"] = {
            "type": "force_buy",
            "rationale": correction.rationale,
            "original_score": original_score,
        }

    elif correction.override_type == "force_sell":
        score["score"] = min(score["score"], 15)
        score["admin_override"] = {
            "type": "force_sell",
            "rationale": correction.rationale,
            "original_score": original_score,
        }

    elif correction.override_type == "ignore":
        # Mark as ignored — the selection engine should skip this symbol
        score["score"] = -1  # below any threshold
        score["admin_override"] = {
            "type": "ignore",
            "rationale": correction.rationale,
            "original_score": original_score,
        }

    elif correction.override_type == "custom_weight_modifier":
        # Adjust component weights for this ticker and recompute
        raw_weights = dict(score.get("raw_components", {}))
        custom_w = correction.weights or {}
        total_raw = sum(raw_weights.values()) if raw_weights else 1
        adjusted_total = 0.0

        for comp, val in raw_weights.items():
            new_weight = custom_w.get(comp)
            if new_weight is not None:
                old_val = raw_weights[comp] * (DEFAULT_COMPONENT_WEIGHTS.get(comp, 1) / total_raw) if total_raw > 0 else 0
                adjusted_total += val * (new_weight / DEFAULT_COMPONENT_WEIGHTS.get(comp, 1))
            else:
                adjusted_total += val

        # Clamp the adjusted score to [0, 100] range
        new_score = max(0, min(100, adjusted_total + score["penalties_applied"]))
        score["score"] = int(round(new_score))
        score["admin_override"] = {
            "type": "custom_weight_modifier",
            "rationale": correction.rationale,
            "original_score": original_score,
            "adjusted_score": new_score,
        }

    return score


def is_ignored(symbol: str, admin_corrections: dict[str, AdminCorrection]) -> bool:
    """Check if a symbol should be ignored due to admin correction."""
    c = admin_corrections.get(symbol)
    return c is not None and c.override_type == "ignore"


# ── Persistent corrections (SQLite) ───────────────────────────────────────────

def persist_correction(
    symbol: str,
    override_type: str,
    rationale: str = "",
    weights: dict | None = None,
) -> AdminCorrection:
    """Add or update a correction in the persistent store."""
    conn = _get_db()
    try:
        _init_db(conn)

        weights_json = json.dumps(weights or {})

        conn.execute("""
            INSERT INTO corrections (symbol, override_type, rationale, weights_json)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                override_type=excluded.override_type,
                rationale=excluded.rationale,
                weights_json=excluded.weights_json,
                updated_at=CURRENT_TIMESTAMP
        """, (symbol, override_type, rationale, weights_json))

        # Log the action
        conn.execute("""
            INSERT INTO correction_log (correction_id, action, details_json)
            SELECT id, 'add', ? FROM corrections WHERE symbol=?
        """, (json.dumps({"type": override_type, "rationale": rationale}), symbol))

        conn.commit()
    finally:
        conn.close()

    return AdminCorrection(symbol=symbol, override_type=override_type, rationale=rationale, weights=weights or {})


def remove_correction(symbol: str) -> bool:
    """Remove a correction from the persistent store."""
    conn = _get_db()
    try:
        _init_db(conn)

        # Get correction ID before deleting
        row = conn.execute("SELECT id FROM corrections WHERE symbol=?", (symbol,)).fetchone()
        if not row:
            return False

        conn.execute("DELETE FROM corrections WHERE symbol=?", (symbol,))

        # Log the action
        conn.execute("""
            INSERT INTO correction_log (correction_id, action, details_json)
            VALUES (?, 'remove', '{}')
        """, (row[0],))

        conn.commit()
        return True
    finally:
        conn.close()


def list_corrections() -> list[AdminCorrection]:
    """List all persistent corrections."""
    conn = _get_db()
    try:
        _init_db(conn)

        rows = conn.execute(
            "SELECT symbol, override_type, rationale, weights_json FROM corrections"
        ).fetchall()

        result = []
        for sym, otype, rat, wj in rows:
            weights = {}
            try:
                weights = json.loads(wj) if isinstance(wj, str) else (wj or {})
            except (json.JSONDecodeError, TypeError):
                pass
            result.append(AdminCorrection(symbol=sym, override_type=otype, rationale=rat, weights=weights))

        return result
    finally:
        conn.close()


def log_scoring_event(
    symbol: str,
    raw_score: float,
    adjusted_score: float,
    override_applied: Optional[str],
    final_decision: str,
) -> None:
    """Log a scoring event for learning module analysis."""
    conn = _get_db()
    try:
        _init_db(conn)

        conn.execute("""
            INSERT INTO scoring_history (symbol, date, raw_score, adjusted_score, override_applied, final_decision)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            symbol,
            date.today().isoformat(),
            raw_score,
            adjusted_score,
            override_applied,
            final_decision,
        ))

        conn.commit()
    finally:
        conn.close()


# ── CLI ───────────────────────────────────────────────────────────────────────

def cli_main() -> int:
    """CLI entry point for admin corrections management."""
    ap = argparse.ArgumentParser(
        description="Admin correction system — add, remove, and list manual overrides.",
    )
    sub = ap.add_subparsers(dest="command", help="Command to run")

    # add
    p_add = sub.add_parser("add", help="Add a correction for a symbol")
    p_add.add_argument("symbol", help="Stock symbol (e.g., THYAO.IS)")
    p_add.add_argument(
        "--type", "-t", required=True, dest="override_type",
        choices=["force_buy", "force_sell", "ignore", "custom_weight_modifier"],
        help="Override type",
    )
    p_add.add_argument("--rationale", "-r", default="", help="Reason for this override")
    p_add.add_argument(
        "--weights", "-w", default=None,
        help='Custom weights JSON (for custom_weight_modifier), e.g. \'{"trend": 30, "momentum": 15}\'',
    )

    # remove
    p_rem = sub.add_parser("remove", help="Remove a correction for a symbol")
    p_rem.add_argument("symbol", help="Stock symbol to remove correction for")

    # list
    sub.add_parser("list", help="List all active corrections")

    args = ap.parse_args()

    if not args.command:
        ap.print_help()
        return 1

    try:
        if args.command == "add":
            weights = json.loads(args.weights) if args.weights else {}
            persist_correction(
                symbol=args.symbol,
                override_type=args.override_type,
                rationale=args.rationale,
                weights=weights,
            )
            print(f"[OK] Added {args.override_type} correction for {args.symbol}: {args.rationale}", file=sys.stderr)

        elif args.command == "remove":
            if remove_correction(args.symbol):
                print(f"[OK] Removed correction for {args.symbol}", file=sys.stderr)
            else:
                print(f"[WARN] No correction found for {args.symbol}", file=sys.stderr)
                return 1

        elif args.command == "list":
            corrections = list_corrections()
            if not corrections:
                print("[INFO] No active corrections.", file=sys.stderr)
            else:
                print(f"{'Symbol':<15} {'Type':<20} {'Rationale'}", file=sys.stderr)
                print("-" * 60, file=sys.stderr)
                for c in corrections:
                    print(f"{c.symbol:<15} {c.override_type:<20} {c.rationale}", file=sys.stderr)

    except Exception as e:
        # Non-blocking fallback if DB is unwritable
        print(f"[ERROR] Admin corrections DB error: {e}", file=sys.stderr)
        return 1

    return 0


# ── Main (standalone) ────────────────────────────────────────────────────────

if __name__ == "__main__":
    raise SystemExit(cli_main())
