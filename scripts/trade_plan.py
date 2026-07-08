#!/usr/bin/env python3
"""
trade_plan.py
=============
Structured Trade Plan Generator.

Takes a scoring result and generates a JSON trade plan with:
- Entry signal (price level, confidence)
- Stop loss placement (technical basis)
- Take profit targets (multiple levels based on R/R)
- Position sizing (based on risk tolerance)
- Time-based exit conditions
- Risk management rules

Usage:
    python3 scripts/trade_plan.py --score scorecard.json --output plan.json
    echo '{"symbol":"BTC/USDT",...}' | python3 scripts/trade_plan.py --stdin

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict
from typing import Optional


def calculate_position_size(
    capital: float,
    entry_price: float,
    stop_loss_price: float,
    risk_per_trade_pct: float = 0.02,
) -> dict:
    """
    Calculate position size based on fixed-fraction risk management.

    Args:
        capital: Total trading capital
        entry_price: Expected entry price
        stop_loss_price: Stop loss price level
        risk_per_trade_pct: Risk per trade as fraction (0.02 = 2%)

    Returns:
        Dict with position size, risk amount, and R:R details
    """
    if entry_price <= 0 or stop_loss_price <= 0:
        return {"error": "Invalid price input"}

    # Distance to stop loss as percentage (works for longs and shorts)
    risk_pct = abs(entry_price - stop_loss_price) / entry_price

    if risk_pct == 0:
        return {"error": "Stop loss at same price as entry"}

    # Risk amount in currency
    risk_amount = capital * risk_per_trade_pct

    # Position size in base asset units (absolute risk per unit)
    position_size = risk_amount / abs(entry_price - stop_loss_price) if entry_price != stop_loss_price else 0

    # Total position value
    position_value = position_size * entry_price if position_size > 0 else 0

    return {
        "position_size": round(position_size, 6),
        "position_value": round(position_value, 2),
        "risk_amount": round(risk_amount, 2),
        "risk_pct_of_capital": risk_per_trade_pct * 100,
        "stop_distance_pct": round(risk_pct * 100, 2),
    }


def calculate_targets(
    entry_price: float,
    stop_loss_price: float,
    direction: str = "long",
    targets_count: int = 3,
) -> list[dict]:
    """
    Calculate multiple take-profit levels based on risk/reward ratios.

    Args:
        entry_price: Entry price
        stop_loss_price: Stop loss price
        direction: 'long' or 'short'
        targets_count: Number of target levels (1-3 recommended)

    Returns:
        List of target dicts with price, R:R ratio, and recommendation
    """
    risk = abs(entry_price - stop_loss_price)
    targets = []

    if direction == "long":
        rr_ratios = [1.0, 2.0, 3.0][:targets_count]
        for i, rr in enumerate(rr_ratios):
            price = entry_price + risk * rr
            targets.append({
                "level": f"TP{i+1}",
                "price": round(price, 6),
                "risk_reward_ratio": rr,
                "distance_pct": round((price / entry_price - 1) * 100, 2),
                "recommendation": "Partial exit" if i == targets_count - 1 else f"Scale out {i+1}",
            })
    else:
        rr_ratios = [1.0, 2.0, 3.0][:targets_count]
        for i, rr in enumerate(rr_ratios):
            price = entry_price - risk * rr
            targets.append({
                "level": f"TP{i+1}",
                "price": round(price, 6),
                "risk_reward_ratio": rr,
                "distance_pct": round((entry_price / price - 1) * 100, 2),
                "recommendation": "Partial exit" if i == targets_count - 1 else f"Scale out {i+1}",
            })

    return targets


def generate_trade_plan(
    symbol: str,
    decision: dict,
    indicators: dict,
    capital: float = 10000.0,
    risk_per_trade_pct: float = 0.02,
) -> dict:
    """
    Generate a complete trade plan from scoring results.

    Args:
        symbol: Trading pair/ticker
        decision: Decision dict from score.py (action, rationale, framing)
        indicators: Indicators dict from indicators.py
        capital: Available trading capital
        risk_per_trade_pct: Risk per trade as fraction of capital

    Returns:
        Complete trade plan JSON-serializable dict
    """
    current_price = indicators.get("close")
    if not current_price:
        return {"error": "No price data available"}

    action = decision.get("action", "")
    action_upper = action.upper()
    is_long_entry = any(kw in action_upper for kw in ["RE-ENTRY", "TACTICAL REBOUND", "BUY", "LONG"])
    is_short_entry = any(kw in action_upper for kw in ["SHORT", "SELL"])
    is_exit = any(kw in action_upper for kw in ["EXIT", "TRIM"])

    if not is_long_entry and not is_short_entry:
        return {
            "symbol": symbol,
            "action": action,
            "status": "no_trade",
            "reason": decision.get("rationale", ""),
            "framing": decision.get("framing", ""),
        }

    direction = "long" if is_long_entry else "short"

    # Stop loss placement — prefer ATR-based if available, fall back to Bollinger Bands
    atr_val = indicators.get("atr14")
    if direction == "long":
        bb_lower = indicators.get("bb_lower") or current_price * 0.95
        if atr_val is not None and atr_val > 0:
            # ATR-based stop loss (2× ATR below entry)
            stop_loss = current_price - (atr_val * 2.0)
            stop_basis = f"ATR({int(indicators.get('atr14', 14))}×{atr_val:.4f}) × 2"
        else:
            buffer = current_price * 0.01 * 2.0
            stop_loss = bb_lower - buffer
            stop_basis = "BB lower band − ATR buffer (fallback)"
    else:
        bb_upper = indicators.get("bb_upper") or current_price * 1.05
        if atr_val is not None and atr_val > 0:
            # ATR-based stop loss (2× ATR above entry)
            stop_loss = current_price + (atr_val * 2.0)
            stop_basis = f"ATR({int(indicators.get('atr14', 14))}×{atr_val:.4f}) × 2"
        else:
            buffer = current_price * 0.01 * 2.0
            stop_loss = bb_upper + buffer
            stop_basis = "BB upper band + ATR buffer (fallback)"

    # Position sizing
    position_info = calculate_position_size(
        capital, current_price, stop_loss, risk_per_trade_pct
    )

    # Take profit targets
    targets = calculate_targets(current_price, stop_loss, direction)

    # Time-based exit conditions
    time_plan = {
        "max_hold_days": 30,
        "review_after_days": [3, 7, 14],
        "trailing_stop_activation_pct": 1.5,
        "notes": [
            "Move stop to breakeven after TP1 is hit",
            "Trailing stop activates at 1.5x risk in profit",
            "Review on each specified day if no target reached",
        ],
    }

    # Confidence scoring (0-1 scale)
    trend_score = indicators.get("ema20") and current_price > indicators["ema20"] and indicators.get("ema20_slope", 0) > 0
    momentum_conf = indicators.get("rsi14", 50) or 50
    if momentum_conf < 40:
        mom_score = 0.3
    elif momentum_conf < 55:
        mom_score = 0.5
    else:
        mom_score = 0.7

    confidence = min(1.0, round((0.6 if trend_score else 0.3) + mom_score * 0.4, 2))

    plan = {
        "symbol": symbol,
        "action": action,
        "direction": direction,
        "status": "active_plan",
        "entry": {
            "price": round(current_price, 6),
            "type": "market" if is_long_entry else "limit",
            "confidence": confidence,
            "rationale": decision.get("rationale", ""),
        },
        "stop_loss": {
            "price": round(stop_loss, 6),
            "basis": stop_basis,
            "distance_pct": round(abs(current_price - stop_loss) / current_price * 100, 2),
        },
        **position_info,
        "targets": targets,
        "time_plan": time_plan,
        "risk_management": {
            "max_positions": 5,
            "correlation_check": True,
            "daily_loss_limit_pct": 3.0,
            "weekly_loss_limit_pct": 8.0,
        },
        "framing": decision.get("framing", ""),
    }

    return plan


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generate structured trade plans from scoring results."
    )
    ap.add_argument("--score", "-s", help="Path to scorecard JSON file")
    ap.add_argument("--stdin", action="store_true", help="Read scorecard from stdin")
    ap.add_argument("--capital", type=float, default=10000.0, help="Trading capital (default: 10000)")
    ap.add_argument("--risk-pct", type=float, default=0.02, help="Risk per trade as fraction (default: 0.02 = 2%%)")
    ap.add_argument("--output", "-o", default=None, help="Output file path")
    args = ap.parse_args()

    # Load scorecard
    if args.stdin:
        raw = sys.stdin.read()
        scorecard = json.loads(raw)
    elif args.score:
        with open(args.score) as f:
            scorecard = json.load(f)
    else:
        print("[ERROR] Provide --score file or use --stdin", file=sys.stderr)
        return 1

    try:
        plan = generate_trade_plan(
            symbol=scorecard.get("symbol", "UNKNOWN"),
            decision=scorecard.get("decision", {}),
            indicators=scorecard.get("indicators", scorecard),
            capital=args.capital,
            risk_per_trade_pct=args.risk_pct,
        )

        output = json.dumps(plan, indent=2, ensure_ascii=False)

        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"[OK] Trade plan saved to {args.output}")
        else:
            print(output)

        return 0
    except Exception as e:
        error_plan = {"error": str(e), "symbol": scorecard.get("symbol", "UNKNOWN")}
        print(json.dumps(error_plan, indent=2, ensure_ascii=False), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
