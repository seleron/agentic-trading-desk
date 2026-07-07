#!/usr/bin/env python3
"""
notification_router.py
======================
Tiered alert system for BIST AI Trader v1.0 with Telegram integration.

Score-based tiered alerts per spec:
  >85 = Strong buy signal (Telegram/Slack)
  70-85 = Watchlist addition
  <70 = No trade

Usage:
    python3 scripts/notification_router.py --input scores.json --output notifications.json
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

logger = logging.getLogger(__name__)


def _send_telegram_message(
    token: str,
    chat_id: str,
    text: str,
    parse_mode: str = "Markdown",
) -> bool:
    """Send a message via the Telegram Bot API. Returns True on success."""
    try:
        import requests  # ccxt transitive dependency; always available
    except ImportError:
        logger.warning("requests library not installed — skipping Telegram delivery")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode,
        # Disable web page preview for cleaner messages
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        if resp.status_code == 200:
            logger.info("Telegram message sent to %s", chat_id)
            return True
        else:
            logger.warning(
                "Telegram API error (%d): %s — status code %d",
                resp.status_code,
                resp.text.strip(),
                resp.status_code,
            )
            return False
    except Exception as exc:
        logger.error("Failed to send Telegram message: %s", exc)
        return False


def _is_in_quiet_hours(quiet_start_hour: int = 23, quiet_end_hour: int = 6) -> bool:
    """Return True if the current hour falls within quiet hours."""
    now_hour = datetime.now().hour
    if quiet_start_hour > quiet_end_hour:
        # Wraps midnight (e.g. 23-06)
        return now_hour >= quiet_start_hour or now_hour < quiet_end_hour
    else:
        return quiet_start_hour <= now_hour < quiet_end_hour


# ---------------------------------------------------------------------------
# Notification dataclass
# ---------------------------------------------------------------------------

@dataclass
class Notification:
    tier: str          # "strong_buy", "watchlist", "no_trade"
    symbol: str
    score: int
    message: str
    action_required: bool  # True = user should act (buy)


def _score_to_tier(score: int) -> tuple[str, str]:
    """Return (tier_label, emoji_prefix) for a given score."""
    if score >= 85:
        return ("strong_buy", "🔵")
    elif score >= 70:
        return ("watchlist", "🟡")
    else:
        return ("no_trade", "⚪")


# ---------------------------------------------------------------------------
# Telegram-formatted message builder
# ---------------------------------------------------------------------------

def _build_telegram_message(
    tier: str,
    symbol: str,
    score: int,
    rationale: list[str],
    trade_plan: Optional[dict] = None,
) -> str:
    """Build a Telegram-compatible Markdown message from notification data."""
    _, prefix = _score_to_tier(score)

    if tier == "strong_buy":
        lines = [
            f"{prefix} *STRONG BUY* — {symbol}",
            f"Score: **{score}/100**",
            "",
        ]
        if trade_plan:
            entry = trade_plan.get("entry_price")
            stop_loss = trade_plan.get("stop_loss")
            targets = trade_plan.get("targets", [])
            if entry is not None:
                lines.append(f"Entry: `{entry}`")
            if stop_loss is not None:
                lines.append(f"Stop Loss: `{stop_loss}`")
            for i, tgt in enumerate(targets):
                if isinstance(tgt, dict) and "price" in tgt:
                    lines.append(f"Target {i+1}: `{tgt['price']}` ({tgt.get('reason', '')})")
                elif isinstance(tgt, (int, float)):
                    lines.append(f"Target {i+1}: `{tgt}`")

        if rationale:
            lines.append("")
            lines.append("Rationale:")
            for r in rationale[:3]:
                lines.append(f"- {r}")

    elif tier == "watchlist":
        lines = [
            f"{prefix} *WATCHLIST ADD* — {symbol}",
            f"Score: **{score}/100**",
            "",
            "Monitor for breakout. Not yet strong enough for a trade.",
        ]
    else:
        return ""  # silent — no message

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# EOD summary builder
# ---------------------------------------------------------------------------

def _build_eod_summary(
    trades_report: dict,
    notifications: list[dict],
) -> str:
    """Build an end-of-day Telegram summary."""
    lines = ["📊 *EOD Summary*", ""]

    wins = trades_report.get("wins", 0)
    losses = trades_report.get("losses", 0)
    open_pos = trades_report.get("open_positions", 0)
    win_rate = trades_report.get("win_rate", 0)
    total_pnl_pct = trades_report.get("total_pnl_pct", 0)

    lines.append(f"Trades today: {wins + losses}")
    if open_pos:
        lines.append(f"Open positions: {open_pos}")
    lines.append(f"Win rate (all time): *{win_rate}%*")
    lines.append(f"Total PnL%: `{total_pnl_pct:.2f}%`")

    strong_buys = sum(1 for n in notifications if n.get("tier") == "strong_buy")
    watchlist_adds = sum(1 for n in notifications if n.get("tier") == "watchlist")
    lines.append("")
    lines.append(f"Today's signals: {strong_buys} strong buy(s), {watchlist_adds} watchlist add(s)")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Core routing logic
# ---------------------------------------------------------------------------

def classify_score(score: int, symbol: str, rationale: list[str]) -> Notification:
    """Classify a single stock score into tiered notification."""
    if score >= 85:
        return Notification(
            tier="strong_buy",
            symbol=symbol,
            score=score,
            message=f"STRONG BUY: {symbol} scored {score}/100. Rationale: {'; '.join(rationale[:3])}",
            action_required=True,
        )
    elif score >= 70:
        return Notification(
            tier="watchlist",
            symbol=symbol,
            score=score,
            message=f"WATCHLIST: {symbol} scored {score}/100. Monitor for breakout.",
            action_required=False,
        )
    else:
        return Notification(
            tier="no_trade",
            symbol=symbol,
            score=score,
            message=f"{symbol} scored {score}/100 — below threshold. No trade.",
            action_required=False,
        )


def route_notifications(
    scores: list[dict],
    selection: dict,
    telegram_config: Optional[dict] = None,
    trade_plans: Optional[list[dict]] = None,
    trades_report: Optional[dict] = None,
) -> list[dict]:
    """Route all scores through tiered notification system.

    Args:
        scores: List of scored symbol dicts.
        selection: Selection output dict with market bias info.
        telegram_config: Dict with 'api_token' and 'chat_id'. If None, no Telegram.
        trade_plans: Optional list of trade plan dicts keyed by symbol for rich messages.
        trades_report: Optional EOD trades report dict for summary generation.

    Returns:
        List of notification dicts (unchanged format).
    """
    notifications = []

    # Track which symbols we've already sent a message to today (dedup)
    sent_today: set[str] = set()

    quiet_start = 23
    quiet_end = 6
    in_quiet_hours = _is_in_quiet_hours(quiet_start, quiet_end)

    trade_plan_map = {}
    if trade_plans:
        for tp in trade_plans:
            sym = tp.get("symbol", "")
            trade_plan_map[sym] = tp

    # Process each scored stock
    for s in scores:
        score_val = s.get("score", 0)
        symbol = s.get("symbol", "UNKNOWN")
        rationale = s.get("rationale", [])

        notif = classify_score(score_val, symbol, rationale)

        # Skip no_trade notifications (silent)
        if notif.tier == "no_trade":
            continue

        # Dedup: one message per symbol per day
        if symbol in sent_today:
            logger.debug("Skipping duplicate notification for %s today", symbol)
            continue  # Skip both Telegram and JSON output

        # Mark as seen (regardless of Telegram config or quiet hours)
        sent_today.add(symbol)

        # Telegram delivery (if configured and not quiet hours)
        if telegram_config:
            token = telegram_config.get("api_token")
            chat_id = telegram_config.get("chat_id")
            if token and chat_id:
                plan = trade_plan_map.get(symbol, {})
                tg_msg = _build_telegram_message(
                    notif.tier, symbol, score_val, rationale, plan
                )
                if tg_msg and not in_quiet_hours:
                    success = _send_telegram_message(token, chat_id, tg_msg)
                    sent_today.add(symbol)  # Always mark as sent to prevent retries
                    logger.info("Telegram alert sent for %s (%s)", symbol, notif.tier)

        notifications.append(asdict(notif))

    # Add market-level notification (always included in JSON output)
    bias = selection.get("market_bias", "neutral")
    no_trade = selection.get("no_trade_day", True)
    avg_score = selection.get("avg_score_all_stocks", 0)

    if bias == "positive" and not no_trade:
        notifications.append({
            "tier": "market_positive",
            "symbol": "BIST50_INDEX",
            "score": round(avg_score),
            "message": f"BIST50 market bias: positive (avg score {avg_score:.1f}). Top picks ready.",
            "action_required": True,
        })
    elif bias == "negative":
        notifications.append({
            "tier": "market_negative",
            "symbol": "BIST50_INDEX",
            "score": round(avg_score),
            "message": f"BIST50 market bias: negative (avg score {avg_score:.1f}). Caution advised.",
            "action_required": False,
        })

    # EOD summary via Telegram if we have trades data and config
    if telegram_config and trades_report and not trades_report.get("no_trades", True):
        token = telegram_config.get("api_token")
        chat_id = telegram_config.get("chat_id")
        if token and chat_id:
            eod_msg = _build_eod_summary(trades_report, notifications)
            if not in_quiet_hours:
                _send_telegram_message(token, chat_id, eod_msg)

    return notifications


# ---------------------------------------------------------------------------
# Config loader (minimal — reads from config.yaml or env vars)
# ---------------------------------------------------------------------------

def load_telegram_config(config_path: str = "config.yaml") -> Optional[dict]:
    """Load Telegram config from config.yaml or environment variables.

    Returns dict with 'api_token' and 'chat_id', or None if not configured.
    """
    # Try config.yaml first
    try:
        import yaml  # optional; falls back to env vars
        with open(config_path) as f:
            cfg = yaml.safe_load(f) or {}
        tg = cfg.get("telegram", {})
        token = tg.get("api_token")
        chat_id = tg.get("chat_id")
        if token and chat_id:
            return {"api_token": str(token), "chat_id": str(chat_id)}
    except (ImportError, FileNotFoundError) as exc:
        logger.debug("Could not load telegram config from %s: %s", config_path, exc)

    # Fall back to environment variables
    token = os.environ.get("TELEGRAM_API_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if token and chat_id:
        return {"api_token": str(token), "chat_id": str(chat_id)}

    logger.warning(
        "Telegram not configured — set telegram.api_token + telegram.chat_id in config.yaml "
        "or TELEGRAM_API_TOKEN / TELEGRAM_CHAT_ID env vars"
    )
    return None


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Tiered notification router for BIST AI Trader v1.0."
    )
    ap.add_argument("--input", "-i", required=True, help="Input JSON with scores + selection")
    ap.add_argument("--output", "-o", default=None, help="Output notifications JSON")
    ap.add_argument(
        "--config", "-c", default="config.yaml",
        help="Config file path (for telegram settings)",
    )
    ap.add_argument(
        "--trade-plans", default=None,
        help="Path to trade_plans.json for rich Telegram messages",
    )
    ap.add_argument(
        "--trades-report", default=None,
        help="Path to EOD trades report JSON for summary",
    )
    args = ap.parse_args()

    try:
        with open(args.input) as f:
            data = json.load(f)
        scores = data.get("scores", [])
        selection = data.get("selection", {})
    except Exception as e:
        print(f"[ERROR] Failed to load input: {e}", file=sys.stderr)
        return 1

    # Load optional trade plans for rich messages
    trade_plans = None
    if args.trade_plans:
        try:
            with open(args.trade_plans) as f:
                trade_plans = json.load(f)
        except Exception as e:
            logger.warning("Could not load trade plans: %s", e)

    # Load optional EOD trades report for summary
    trades_report = None
    if args.trades_report:
        try:
            with open(args.trades_report) as f:
                trades_report = json.load(f)
        except Exception as e:
            logger.warning("Could not load trades report: %s", e)

    # Load Telegram config
    telegram_config = load_telegram_config(args.config)

    notifications = route_notifications(
        scores, selection,
        telegram_config=telegram_config,
        trade_plans=trade_plans,
        trades_report=trades_report,
    )
    output_text = json.dumps(notifications, indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"[OK] Notifications saved to {args.output}", file=sys.stderr)
    else:
        print(output_text)

    # Summary
    strong = sum(1 for n in notifications if n["tier"] == "strong_buy")
    watchlist = sum(1 for n in notifications if n["tier"] == "watchlist")
    print(f"\n[SUMMARY]", file=sys.stderr)
    print(f"  Strong buys:     {strong}", file=sys.stderr)
    print(f"  Watchlist adds:  {watchlist}", file=sys.stderr)
    print(f"  Total processed: {len(notifications)}", file=sys.stderr)

    if telegram_config:
        print("  Telegram:        enabled", file=sys.stderr)
    else:
        print("  Telegram:        not configured (skipped)", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
