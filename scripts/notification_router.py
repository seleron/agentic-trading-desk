#!/usr/bin/env python3
"""
notification_router.py
======================
Tiered alert system for BIST AI Trader v1.0.

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
import sys
from dataclasses import dataclass, asdict


@dataclass
class Notification:
    tier: str          # "strong_buy", "watchlist", "no_trade"
    symbol: str
    score: int
    message: str
    action_required: bool  # True = user should act (buy)


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


def route_notifications(scores: list[dict], selection: dict) -> list[dict]:
    """Route all scores through tiered notification system."""
    notifications = []

    # Process each scored stock
    for s in scores:
        notif = classify_score(
            s["score"],
            s.get("symbol", "UNKNOWN"),
            s.get("rationale", []),
        )
        notifications.append(asdict(notif))

    # Add market-level notification
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

    return notifications


def main() -> int:
    ap = argparse.ArgumentParser(description="Tiered notification router for BIST AI Trader v1.0.")
    ap.add_argument("--input", "-i", required=True, help="Input JSON with scores + selection")
    ap.add_argument("--output", "-o", default=None, help="Output notifications JSON")
    args = ap.parse_args()

    try:
        with open(args.input) as f:
            data = json.load(f)
        scores = data.get("scores", [])
        selection = data.get("selection", {})
    except Exception as e:
        print(f"[ERROR] Failed to load input: {e}", file=sys.stderr)
        return 1

    notifications = route_notifications(scores, selection)
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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
