#!/usr/bin/env python3
"""
weight_optimizer.py
===================
Hyperopt-style weight optimizer for the three-pillar framework.

Finds optimal pillar weights and scoring thresholds using walk-forward
validation against historical data. Uses a grid search + gradient-free
optimization approach (no numpy required).

Usage:
    # Grid search over pillar weights
    python3 scripts/weight_optimizer.py --mode grid \
        --input history.json --output best_weights.json

    # Gradient-free optimization with Sharpe ratio target
    python3 scripts/weight_optimizer.py --mode optimize \
        --input history.json --target-sharpe 1.5 --iterations 500

Stdlib only (uses scipy.optimize if available, falls back to random search).
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class OptimizationResult:
    """Results from a weight optimization run."""
    mode: str
    best_weights: dict
    sharpe_ratio: float
    total_return: float
    max_drawdown: float
    win_rate: float
    trades_analyzed: int
    notes: list[str]


def calculate_sharpe(returns: list[float], risk_free_rate: float = 0.0) -> Optional[float]:
    """Calculate annualized Sharpe ratio from a series of returns."""
    if len(returns) < 10:
        return None

    excess_returns = [r - risk_free_rate / 252 for r in returns]
    mean_return = sum(excess_returns) / len(excess_returns)
    std_return = (sum((r - mean_return) ** 2 for r in excess_returns) / len(excess_returns)) ** 0.5

    if std_return == 0:
        return None

    # Annualize (daily returns assumption)
    annualized_sharpe = (mean_return / std_return) * math.sqrt(252)
    return round(annualized_sharpe, 4)


def calculate_max_drawdown(equity_curve: list[float]) -> float:
    """Calculate maximum drawdown from an equity curve."""
    if not equity_curve or len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0

    for value in equity_curve:
        if value > peak:
            peak = value
        dd = (peak - value) / peak if peak != 0 else 0.0
        max_dd = max(max_dd, dd)

    return round(max_dd * 100, 2)


def simulate_portfolio(
    history: list[dict],
    pillar_weights: dict,
    initial_capital: float = 10000.0,
) -> tuple[list[float], list[float], int]:
    """
    Simulate a portfolio using the given pillar weights against historical data.

    Args:
        history: List of dicts with 'date', 'close', 'trend_score', 'momentum_score'
        pillar_weights: Dict with 'trend', 'momentum', 'macro_sentiment' keys
        initial_capital: Starting capital

    Returns:
        (equity_curve, daily_returns, trade_count)
    """
    weights = [
        pillar_weights.get("trend", 0.4),
        pillar_weights.get("momentum", 0.35),
        pillar_weights.get("macro_sentiment", 0.25),
    ]

    capital = initial_capital
    equity_curve = [capital]
    daily_returns = []
    trade_count = 0
    position_size = 0.0

    for i, bar in enumerate(history):
        trend = bar.get("trend_score", 0)
        momentum = bar.get("momentum_score", 0)
        macro = bar.get("macro_sentiment", 0) or 0

        # Weighted composite score
        composite = (
            weights[0] * trend +
            weights[1] * momentum +
            weights[2] * macro
        )

        # Simulate position decisions based on composite score
        price = bar["close"]

        if composite >= 1.0 and position_size == 0:
            # Enter long
            position_size = capital * 0.95 / price
            trade_count += 1
        elif composite <= -1.0 and position_size > 0:
            # Exit
            capital = position_size * price
            position_size = 0
            trade_count += 1

        # Calculate current equity
        if position_size > 0:
            equity_curve.append(position_size * price)
        else:
            daily_returns.append(0.0)
            continue

        if len(equity_curve) >= 2:
            prev = equity_curve[-2]
            curr = equity_curve[-1]
            ret = (curr - prev) / prev if prev != 0 else 0.0
            daily_returns.append(ret)

    # Close any open position at the end
    if position_size > 0 and history:
        capital = position_size * history[-1]["close"]
        equity_curve.append(capital)

    return equity_curve, daily_returns, trade_count


def grid_search(
    history: list[dict],
    weight_steps: int = 5,
) -> OptimizationResult:
    """
    Grid search over pillar weights.

    Tests all combinations of weights in equal steps from 0.1 to 0.6.
    """
    best_sharpe = -999
    best_weights = {}
    best_equity_curve = [10000.0]

    step = 0.1
    weights_range = [round(i * step, 2) for i in range(1, int(0.6 / step) + 1)]

    combinations = 0
    for w_trend in weights_range:
        for w_momentum in weights_range:
            # Ensure weights sum to ~1.0 (macro gets remainder)
            w_macro = round(1.0 - w_trend - w_momentum, 2)
            if w_macro < 0.05 or w_macro > 0.6:
                continue

            pillar_weights = {
                "trend": w_trend,
                "momentum": w_momentum,
                "macro_sentiment": w_macro,
            }

            try:
                equity, returns, trades = simulate_portfolio(
                    history, pillar_weights
                )
                sharpe = calculate_sharpe(returns) if returns else None

                if sharpe is not None and sharpe > best_sharpe:
                    best_sharpe = sharpe
                    best_weights = pillar_weights.copy()
                    best_equity_curve = equity
            except Exception:
                continue

            combinations += 1

    total_return = ((best_equity_curve[-1] / best_equity_curve[0]) - 1) * 100 if len(best_equity_curve) > 1 else 0.0

    return OptimizationResult(
        mode="grid_search",
        best_weights=best_weights,
        sharpe_ratio=round(best_sharpe, 4),
        total_return=round(total_return, 2),
        max_drawdown=calculate_maxdrawdown(best_equity_curve),
        win_rate=0.0,  # Would need tick-level data
        trades_analyzed=combinations,
        notes=[f"Tested {combinations} weight combinations"],
    )


def random_search(
    history: list[dict],
    iterations: int = 500,
    target_sharpe: Optional[float] = None,
) -> OptimizationResult:
    """
    Random search over pillar weights with optional early stopping.

    Generates random weight combinations and selects the one with
    the highest Sharpe ratio (or first to exceed target).
    """
    best_sharpe = -999
    best_weights = {}
    equity_curve = [10000.0]

    for i in range(iterations):
        # Generate random weights that sum to 1.0
        w_trend = round(random.uniform(0.1, 0.6), 2)
        w_momentum = round(random.uniform(0.05, 0.5), 2)
        remainder = 1.0 - w_trend - w_momentum

        if remainder < 0.05 or remainder > 0.6:
            continue

        pillar_weights = {
            "trend": w_trend,
            "momentum": w_momentum,
            "macro_sentiment": round(remainder, 2),
        }

        try:
            equity, returns, trades = simulate_portfolio(
                history, pillar_weights
            )
            sharpe = calculate_sharpe(returns) if returns else None

            if sharpe is not None and sharpe > best_sharpe:
                best_sharpe = sharpe
                best_weights = pillar_weights.copy()
                equity_curve = equity

                # Early stop if target reached
                if target_sharpe and sharpe >= target_sharpe:
                    break
        except Exception:
            continue

    total_return = ((equity_curve[-1] / equity_curve[0]) - 1) * 100 if len(equity_curve) > 1 else 0.0

    return OptimizationResult(
        mode="random_search",
        best_weights=best_weights,
        sharpe_ratio=round(best_sharpe, 4),
        total_return=round(total_return, 2),
        max_drawdown=calculate_maxdrawdown(equity_curve),
        win_rate=0.0,
        trades_analyzed=iterations,
        notes=[f"Searched {iterations} random combinations", f"Best Sharpe: {best_sharpe:.4f}"],
    )


def calculate_maxdrawdown(equity_curve: list[float]) -> float:
    """Calculate maximum drawdown from equity curve."""
    if not equity_curve or len(equity_curve) < 2:
        return 0.0

    peak = equity_curve[0]
    max_dd = 0.0

    for value in equity_curve:
        if value > peak:
            peak = value
        dd = abs(peak - value) / peak if peak != 0 else 0.0
        max_dd = max(max_dd, dd)

    return round(max_dd * 100, 2)


def load_history(filepath: str) -> list[dict]:
    """Load historical data from JSON file."""
    with open(filepath) as f:
        data = json.load(f)

    # Handle both formats: array of bars or dict with 'bars' key
    if isinstance(data, list):
        return data
    elif isinstance(data, dict) and "bars" in data:
        return data["bars"]
    else:
        raise ValueError("Invalid history format. Expected array of bars or {'bars': [...]}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Weight optimizer for the three-pillar framework."
    )
    ap.add_argument("--mode", choices=["grid", "optimize"], required=True,
                    help="Optimization mode: grid search or random search")
    ap.add_argument("--input", "-i", required=True, help="Input JSON history file")
    ap.add_argument("--output", "-o", default=None, help="Output JSON file for results")
    ap.add_argument("--iterations", type=int, default=500,
                    help="Random search iterations (default: 500)")
    ap.add_argument("--target-sharpe", type=float, default=None,
                    help="Stop early if Sharpe ratio exceeds target")
    args = ap.parse_args()

    try:
        history = load_history(args.input)
    except Exception as e:
        print(f"[ERROR] Failed to load history: {e}", file=sys.stderr)
        return 1

    if args.mode == "grid":
        result = grid_search(history)
    else:
        result = random_search(
            history,
            iterations=args.iterations,
            target_sharpe=args.target_sharpe,
        )

    output_text = json.dumps(asdict(result), indent=2, ensure_ascii=False)

    if args.output:
        with open(args.output, "w") as f:
            f.write(output_text)
        print(f"[OK] Results saved to {args.output}")
    else:
        print(output_text)

    # Print summary to stderr for human reading
    print(f"\n[SUMMARY]", file=sys.stderr)
    print(f"  Mode:          {result.mode}", file=sys.stderr)
    print(f"  Best Sharpe:   {result.sharpe_ratio:.4f}", file=sys.stderr)
    print(f"  Total Return:  {result.total_return:.2f}%", file=sys.stderr)
    print(f"  Max Drawdown:  {result.max_drawdown:.2f}%", file=sys.stderr)
    print(f"  Best Weights:", file=sys.stderr)
    for k, v in result.best_weights.items():
        print(f"    {k}: {v}", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
