#!/usr/bin/env python3
"""
trade_plan.py
=============
Structured Trade Plan Generator.

Takes a scoring result and generates a JSON trade plan with:
- Entry signal (price level, confidence)
- Stop loss placement (fixed percentage or ATR-scaled, see stop_loss_method)
- Take profit targets (R/R ladder in fixed_pct mode, ATR multiples in atr mode)
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
import os
import sys
from dataclasses import asdict
from typing import Optional


# ── Stop / target method configuration (backlog #008) ────────────────────────
# "fixed_pct" (default) keeps the historical fixed-percentage stop and the
# R/R target ladder. "atr" scales the stop and the targets with current
# volatility (Wilder ATR from indicators.py), which is what the BIST
# volatility regimes call for.
STOP_LOSS_METHODS = ("fixed_pct", "atr")
DEFAULT_STOP_LOSS_METHOD = "fixed_pct"
DEFAULT_FIXED_STOP_PCT = 0.05
DEFAULT_ATR_STOP_MULTIPLIER = 2.0
DEFAULT_ATR_TP_MULTIPLIERS = (1.5, 3.0)

# Repo-level config.yaml (one level up from scripts/).
DEFAULT_CONFIG_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config.yaml"
)


def load_config(config_path: str = "config.yaml") -> dict:
    """Load config.yaml into a dict; {} when absent/unreadable or PyYAML missing."""
    try:
        import yaml
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


def resolve_stop_settings(
    config: Optional[dict] = None,
    stop_loss_method: Optional[str] = None,
    stop_atr_multiplier: Optional[float] = None,
    fixed_stop_pct: Optional[float] = None,
) -> dict:
    """Resolve stop/target settings: explicit arg > config.yaml > default.

    config.yaml keys:
        trade_plan.stop_loss_method     "fixed_pct" | "atr"   (default fixed_pct)
        trade_plan.stop_loss_pct        fixed-mode stop distance as a fraction
        trade_plan.tp1_atr_multiplier   atr-mode TP1 multiple (default 1.5)
        trade_plan.tp2_atr_multiplier   atr-mode TP2 multiple (default 3.0)
        scoring.stop_atr_multiplier     stop = entry -/+ ATR x multiple (default 2.0)

    Raises:
        ValueError: unknown stop_loss_method or a non-numeric multiplier.
    """
    cfg = (config or {}).get("trade_plan") or {}
    scoring_cfg = (config or {}).get("scoring") or {}

    method = str(
        stop_loss_method or cfg.get("stop_loss_method") or DEFAULT_STOP_LOSS_METHOD
    ).strip().lower()
    if method not in STOP_LOSS_METHODS:
        raise ValueError(
            f"Unknown stop_loss_method {method!r}; expected one of {STOP_LOSS_METHODS}"
        )

    def _num(override, cfg_value, default, name):
        raw = override if override is not None else cfg_value
        try:
            return float(default if raw is None else raw)
        except (TypeError, ValueError):
            raise ValueError(f"{name} must be numeric, got {raw!r}")

    fixed_pct = _num(fixed_stop_pct, cfg.get("stop_loss_pct"),
                     DEFAULT_FIXED_STOP_PCT, "trade_plan.stop_loss_pct")
    atr_mult = _num(stop_atr_multiplier, scoring_cfg.get("stop_atr_multiplier"),
                    DEFAULT_ATR_STOP_MULTIPLIER, "scoring.stop_atr_multiplier")
    tp1 = _num(None, cfg.get("tp1_atr_multiplier"),
               DEFAULT_ATR_TP_MULTIPLIERS[0], "trade_plan.tp1_atr_multiplier")
    tp2 = _num(None, cfg.get("tp2_atr_multiplier"),
               DEFAULT_ATR_TP_MULTIPLIERS[1], "trade_plan.tp2_atr_multiplier")

    if not 0 < fixed_pct < 1:
        raise ValueError(f"trade_plan.stop_loss_pct must be in (0, 1), got {fixed_pct}")
    if atr_mult <= 0:
        raise ValueError(f"scoring.stop_atr_multiplier must be > 0, got {atr_mult}")

    return {
        "stop_loss_method": method,
        "fixed_stop_pct": fixed_pct,
        "stop_atr_multiplier": atr_mult,
        "atr_tp_multipliers": (tp1, tp2),
    }


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


def calculate_atr_targets(
    entry_price: float,
    atr_value: float,
    direction: str = "long",
    stop_distance: Optional[float] = None,
    multipliers: tuple = DEFAULT_ATR_TP_MULTIPLIERS,
) -> list[dict]:
    """Volatility-scaled take-profit ladder: TPn = entry +/- (ATR x multiple).

    Used by the "atr" stop method so target distance tracks the same regime as
    the stop (standard 1.5x / 3.0x ATR framework).
    """
    targets = []
    for i, mult in enumerate(multipliers):
        offset = atr_value * mult
        price = entry_price + offset if direction == "long" else entry_price - offset
        targets.append({
            "level": f"TP{i+1}",
            "price": round(price, 6),
            "risk_reward_ratio": round(offset / stop_distance, 2) if stop_distance else None,
            "atr_multiple": mult,
            "distance_pct": round(abs(price / entry_price - 1) * 100, 2),
            "recommendation": "Partial exit" if i == len(multipliers) - 1 else f"Scale out {i+1}",
        })
    return targets


def generate_trade_plan(
    symbol: str,
    decision: dict,
    indicators: dict,
    capital: float = 10000.0,
    risk_per_trade_pct: float = 0.02,
    config: Optional[dict] = None,
    stop_loss_method: Optional[str] = None,
    stop_atr_multiplier: Optional[float] = None,
    fixed_stop_pct: Optional[float] = None,
) -> dict:
    """
    Generate a complete trade plan from scoring results.

    Args:
        symbol: Trading pair/ticker
        decision: Decision dict from score.py (action, rationale, framing)
        indicators: Indicators dict from indicators.py
        capital: Available trading capital
        risk_per_trade_pct: Risk per trade as fraction of capital
        config: Parsed config.yaml mapping (trade_plan.* / scoring.* keys); when
                omitted every stop setting falls back to its default, i.e.
                `stop_loss_method="fixed_pct"` — the historical behaviour
        stop_loss_method: Override for config's trade_plan.stop_loss_method
        stop_atr_multiplier: Override for config's scoring.stop_atr_multiplier
        fixed_stop_pct: Override for config's trade_plan.stop_loss_pct

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

    # Stop / target settings — config-driven, default "fixed_pct" (backlog #008).
    settings = resolve_stop_settings(
        config,
        stop_loss_method=stop_loss_method,
        stop_atr_multiplier=stop_atr_multiplier,
        fixed_stop_pct=fixed_stop_pct,
    )
    method = settings["stop_loss_method"]

    atr_val = indicators.get("atr14")
    if atr_val is not None and atr_val <= 0:
        atr_val = None  # a zero/None ATR (warmup) cannot size a volatility stop

    # +1 → stop below entry (long), -1 → stop above entry (short).
    side = 1 if direction == "long" else -1

    if method == "atr" and atr_val is not None:
        stop_distance = atr_val * settings["stop_atr_multiplier"]
        stop_basis = f"ATR {atr_val:.4f} × {settings['stop_atr_multiplier']:g}"
    else:
        stop_distance = current_price * settings["fixed_stop_pct"]
        stop_basis = f"fixed {settings['fixed_stop_pct'] * 100:.2f}% of entry"
        if method == "atr":
            stop_basis += " (ATR unavailable — fixed_pct fallback)"

    stop_loss = current_price - side * stop_distance

    # Position sizing
    position_info = calculate_position_size(
        capital, current_price, stop_loss, risk_per_trade_pct
    )

    # Take profit targets — ATR multiples with the atr method, R/R ladder otherwise
    if method == "atr" and atr_val is not None:
        targets = calculate_atr_targets(
            current_price, atr_val, direction,
            stop_distance=stop_distance,
            multipliers=settings["atr_tp_multipliers"],
        )
    else:
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
    # NOTE: compute() always emits ema20_slope / rsi14 keys but sets them to None
    # during indicator warmup, so `.get(k, default)` returns None (not the default).
    # Guard explicitly, otherwise `None > 0` raises TypeError for any short-history
    # symbol that has cleared its EMA20.
    ema20 = indicators.get("ema20")
    ema20_slope = indicators.get("ema20_slope")
    trend_score = (
        ema20 is not None
        and current_price > ema20
        and ema20_slope is not None
        and ema20_slope > 0
    )
    rsi14 = indicators.get("rsi14")
    momentum_conf = rsi14 if rsi14 is not None else 50
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
        # Reported back so the orchestrator can tell the user how the stop was sized.
        "stop_loss_method": method,
        "atr_value": round(atr_val, 6) if atr_val is not None else None,
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
    ap.add_argument("--config", "-c", default=DEFAULT_CONFIG_PATH,
                    help="config.yaml path (stop_loss_method / stop_atr_multiplier live here)")
    ap.add_argument("--stop-loss-method", choices=list(STOP_LOSS_METHODS), default=None,
                    help="Override config trade_plan.stop_loss_method (default: fixed_pct)")
    ap.add_argument("--stop-atr-multiplier", type=float, default=None,
                    help="Override config scoring.stop_atr_multiplier (default: 2.0)")
    ap.add_argument("--stop-loss-pct", type=float, default=None,
                    help="Override config trade_plan.stop_loss_pct (default: 0.05)")
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
            config=load_config(args.config),
            stop_loss_method=args.stop_loss_method,
            stop_atr_multiplier=args.stop_atr_multiplier,
            fixed_stop_pct=args.stop_loss_pct,
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
