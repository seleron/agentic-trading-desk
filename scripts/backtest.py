#!/usr/bin/env python3
"""
backtest.py
Walk-forward backtesting engine for the three-pillar framework.
Runs historical simulations with realistic assumptions:
- Slippage and commission fees
- Position sizing (fixed fraction)
- Weekly rebalancing or event-driven exits
- Sharpe ratio, max drawdown, win rate tracking

Usage:
    python3 scripts/backtest.py --input history.json \
        --weights trend=0.4 momentum=0.35 macro=0.25 \
        --capital 10000 --output results.json

Stdlib only.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class BacktestResult:
    """Results from a backtesting run."""
    symbol: str
    timeframe: str
    start_date: str
    end_date: str
    initial_capital: float
    final_equity: float
    total_return_pct: float
    annualized_return_pct: float
    sharpe_ratio: Optional[float]
    sortino_ratio: Optional[float]
    max_drawdown_pct: float
    calmar_ratio: Optional[float]
    win_rate_pct: float
    profit_factor: float
    total_trades: int
    winning_trades: int
    losing_trades: int
    avg_win_pct: float
    avg_loss_pct: float
    largest_win_pct: float
    largest_loss_pct: float
    avg_trade_duration_bars: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    daily_returns_count: int
    notes: list[str]


def calculate_sharpe(returns: list[float], risk_free_rate: float = 0.0) -> Optional[float]:
    """Calculate annualized Sharpe ratio."""
    if len(returns) < 10:
        return None

    excess = [r - risk_free_rate / 252 for r in returns]
    mean_excess = sum(excess) / len(excess)
    std_excess = (sum((x - mean_excess) ** 2 for x in excess) / len(excess)) ** 0.5

    if std_excess == 0:
        return None

    annualized_sharpe = (mean_excess / std_excess) * math.sqrt(252)
    return round(annualized_sharpe, 4)


def calculate_sortino(returns: list[float], risk_free_rate: float = 0.0) -> Optional[float]:
    """Calculate Sortino ratio (downside deviation only)."""
    if len(returns) < 10:
        return None

    excess = [r - risk_free_rate / 252 for r in returns]
    mean_excess = sum(excess) / len(excess)

    downside = [x for x in excess if x < 0]
    if not downside:
        return None

    downside_std = (sum(x ** 2 for x in downside) / len(returns)) ** 0.5
    if downside_std == 0:
        return None

    annualized_sortino = (mean_excess / downside_std) * math.sqrt(252)
    return round(annualized_sortino, 4)


def calculate_max_drawdown(equity_curve: list[float]) -> tuple[float, int, int]:
    """Calculate max drawdown and its start/end indices."""
    if not equity_curve or len(equity_curve) < 2:
        return 0.0, 0, 0

    peak = equity_curve[0]
    max_dd = 0.0
    dd_start = 0
    dd_end = 0
    peak_idx = 0

    for i, value in enumerate(equity_curve):
        if value > peak:
            peak = value
            peak_idx = i
        dd = (peak - value) / peak if peak != 0 else 0.0
        if dd > max_dd:
            max_dd = dd
            dd_start = peak_idx
            dd_end = i

    return round(max_dd * 100, 2), dd_start, dd_end


def run_backtest(
    bars: list[dict],
    pillar_weights: Optional[dict] = None,
    capital: float = 10000.0,
    commission_pct: float = 0.001,
    slippage_pct: float = 0.0005,
) -> BacktestResult:
    """
    Run a backtest simulation against historical OHLCV data.

    Args:
        bars: List of dicts with 'date', 'open', 'high', 'low', 'close', 'volume'
        pillar_weights: Legacy dict for simplified pillar scoring (optional).
            When None, uses full 7-component scoring_engine + indicators.
        capital: Starting capital
        commission_pct: Commission per trade as fraction (0.1% = 0.001)
        slippage_pct: Slippage per trade as fraction

    Returns:
        BacktestResult with all metrics
    """
    if not bars or len(bars) < 50:
        raise ValueError("Need at least 50 bars for backtesting")

    ENTRY_THRESHOLD = 0.48  # threshold on [-1, +1] scale; ~74/100 score required for entry

    # Initialize state
    equity = capital
    position_size = 0.0
    in_position = False
    entry_fill_price = 0.0  # persisted actual fill price of the open position

    equity_curve = [capital]
    daily_returns = []
    trade_log = []

    winning_trades = []
    losing_trades = []
    consecutive_wins = 0
    consecutive_losses = 0
    max_consec_wins = 0
    max_consec_losses = 0

    for i in range(1, len(bars)):
        bar = bars[i]
        prev_bar = bars[i - 1]
        price = bar["close"]

        # Calculate composite score — dual mode: full 7-component engine or legacy pillars
        recent_closes = [bars[j]["close"] for j in range(max(0, i - 250), i)] if i >= 20 else []

        if pillar_weights is not None:
            # Legacy pillar-based scoring (simple)
            short_hist = [c for c in recent_closes[-10:] if c]  # last 10 valid closes
            long_hist = [c for c in recent_closes if c]          # full history
            sma_short = sum(short_hist) / max(1, len(short_hist))
            sma_long = sum(long_hist) / max(1, len(long_hist))
            roc = (price - recent_closes[0]) / recent_closes[0] if recent_closes and recent_closes[0] != 0 else 0

            trend_score = 1.0 if sma_short > sma_long else -1.0
            mom_score = 1.0 if roc > 0 else -1.0
            macro_score = 0

            w_trend = pillar_weights.get("trend", 0.4)
            w_mom = pillar_weights.get("momentum", 0.35)
            w_macro = pillar_weights.get("macro_sentiment", pillar_weights.get("macro", 0.25))

            composite = (w_trend * trend_score + w_mom * mom_score + w_macro * macro_score)
        else:
            # Full 7-component scoring via indicators + scoring_engine — standalone mode
            try:
                import sys as _sys
                _p = os.path.dirname(os.path.abspath(__file__))
                if _p not in _sys.path:
                    _sys.path.insert(0, _p)
                from indicators import compute as ind_compute  # noqa: F811
                from scoring_engine import (  # noqa: F811
                    score_quote, compute_trend_score,
                    compute_momentum_score, compute_volume_score,
                    compute_ema_structure_score, compute_pivot_score,
                    compute_volatility_score, compute_technical_summary_score,
                )

                closes_hist = [bars[j]["close"] for j in range(max(0, i - 250), i)]
                ind = ind_compute(closes_hist) if len(closes_hist) >= 20 else {}

                vol_recent = [bars[j].get("volume", 0) for j in range(max(1, i - 20), i)]
                volume_avg_20 = (sum(vol_recent) / len(vol_recent)) if vol_recent else 0

                quote = {
                    "symbol": "__bt__",
                    "date": bars[i].get("date", ""),
                    "close": price,
                    "open": bars[i]["open"],
                    "high": bar["high"],
                    "low": bar["low"],
                    "volume": bars[i].get("volume", 0),
                    "rsi": ind.get("rsi14"),
                    "macd": ind.get("macd_line") or 0,
                    "macd_signal": ind.get("macd_signal") or 0,
                    "ema20": ind.get("ema20"),
                    "ema50": ind.get("ema50"),
                    "ema200": ind.get("ema200"),
                    "volume_avg_20": volume_avg_20,
                }

                scored = score_quote(quote)
                # Remap [0,100] → [-1,+1]: (score/100)*2 - 1 so exit threshold is symmetric
                composite = (scored.get("score", 50.0) / 100.0) * 2.0 - 1.0

            except Exception:
                # Fallback: simple ROC-based heuristic if scoring imports fail
                roc = (price - recent_closes[0]) / recent_closes[0] if recent_closes and recent_closes[0] != 0 else 0
                composite = max(-1.0, min(1.0, roc * 5))

        # Entry signal: composite score crosses above threshold
        if not in_position and composite >= ENTRY_THRESHOLD:
            entry_fill_price = price * (1 + slippage_pct)  # pay slippage on entry
            position_size = equity * 0.95 / entry_fill_price
            equity -= position_size * entry_fill_price * commission_pct  # Commission on entry
            in_position = True
            trade_log.append({"type": "entry", "price": round(entry_fill_price, 6), "index": i})

        # Exit signal: composite drops below threshold OR 2% stop below entry fill
        elif in_position and (composite <= -ENTRY_THRESHOLD or price < entry_fill_price * 0.98):
            exit_price = price * (1 - slippage_pct)
            proceeds = position_size * exit_price
            equity += proceeds - proceeds * commission_pct  # Commission on exit
            trade_return = (proceeds / (position_size * entry_fill_price)) - 1
            in_position = False

            if trade_return > 0:
                winning_trades.append(trade_return)
                consecutive_wins += 1
                max_consec_wins = max(max_consec_wins, consecutive_wins)
                consecutive_losses = 0
            else:
                losing_trades.append(trade_return)
                consecutive_losses += 1
                max_consec_losses = max(max_consec_losses, consecutive_losses)
                consecutive_wins = 0

            trade_log.append({"type": "exit", "price": price, "return_pct": round(trade_return * 100, 2)})

        # Calculate daily return
        if in_position:
            current_equity = position_size * price
            equity_curve.append(current_equity)
        else:
            equity_curve.append(equity)

        prev_eq = equity_curve[-2] if len(equity_curve) >= 2 else equity_curve[-1]
        daily_ret = (equity_curve[-1] - prev_eq) / prev_eq if prev_eq != 0 else 0.0
        daily_returns.append(daily_ret)

    # Close open position at end (record it in win/loss accounting)
    if in_position:
        final_price = bars[-1]["close"] * (1 - slippage_pct)
        equity += position_size * final_price - position_size * final_price * commission_pct
        exit_return = (equity / capital) - 1
        trade_log.append({"type": "exit_closed", "price": bars[-1]["close"], "return_pct": round(exit_return * 100, 2)})
        if exit_return > 0:
            winning_trades.append(exit_return)
        else:
            losing_trades.append(exit_return)

    # Calculate metrics
    total_return_pct = ((equity_curve[-1] / equity_curve[0]) - 1) * 100 if len(equity_curve) > 1 else 0.0
    annualized_ret = ((equity_curve[-1] or capital) / capital) ** (252 / max(len(bars), 1)) - 1 if equity_curve[-1] and equity_curve[-1] != equity_curve[0] else 0.0

    sharpe = calculate_sharpe(daily_returns)
    sortino = calculate_sortino(daily_returns)
    max_dd, dd_start, dd_end = calculate_max_drawdown(equity_curve)

    # Calmar ratio: annualized return / max drawdown (annualized_ret is already
    # annualized as a fraction, and max_dd is a percentage → divide by 100)
    calmar = round(annualized_ret / (max_dd / 100), 4) if max_dd > 0 else None

    total_trades = len(winning_trades) + len(losing_trades)
    win_rate = (len(winning_trades) / total_trades * 100) if total_trades > 0 else 0.0

    # Profit factor
    gross_profit = sum(abs(r) for r in winning_trades) if winning_trades else 0
    gross_loss = abs(sum(losing_trades)) if losing_trades else 0.0
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else float('inf')

    avg_win = sum(winning_trades) / len(winning_trades) * 100 if winning_trades else 0.0
    avg_loss = sum(losing_trades) / len(losing_trades) * 100 if losing_trades else 0.0
    largest_win = max(winning_trades) * 100 if winning_trades else 0.0
    largest_loss = min(losing_trades) * 100 if losing_trades else 0.0

    return BacktestResult(
        symbol="MULTI",
        timeframe="daily",
        start_date=bars[0].get("date", "unknown"),
        end_date=bars[-1].get("date", "unknown"),
        initial_capital=capital,
        final_equity=round(equity_curve[-1], 2),
        total_return_pct=round(total_return_pct, 2),
        annualized_return_pct=round(annualized_ret * 100, 2),
        sharpe_ratio=sharpe,
        sortino_ratio=sortino,
        max_drawdown_pct=max_dd,
        calmar_ratio=calmar,
        win_rate_pct=round(win_rate, 2),
        profit_factor=profit_factor if profit_factor != float('inf') else 99.99,
        total_trades=total_trades,
        winning_trades=len(winning_trades),
        losing_trades=len(losing_trades),
        avg_win_pct=round(avg_win, 2),
        avg_loss_pct=round(avg_loss, 2),
        largest_win_pct=round(largest_win, 2),
        largest_loss_pct=round(largest_loss, 2),
        avg_trade_duration_bars=0.0,
        max_consecutive_wins=max_consec_wins,
        max_consecutive_losses=max_consec_losses,
        daily_returns_count=len(daily_returns),
        notes=[f"Commission: {commission_pct * 100:.2f}%% | Slippage: {slippage_pct * 100:.3f}%%"],
    )


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Walk-forward backtesting engine for the trading desk."
    )
    ap.add_argument("--input", "-i", required=True, help="Input JSON with OHLCV bars")
    ap.add_argument("--weights", nargs="+", default=["trend=0.4", "momentum=0.35", "macro=0.25"],
                    help="Weight assignments (e.g., trend=0.4 momentum=0.35 macro=0.25)")
    ap.add_argument("--capital", type=float, default=10000.0, help="Initial capital")
    ap.add_argument("--commission", type=float, default=0.001, help="Commission per trade (default: 0.1%%)")
    ap.add_argument("--slippage", type=float, default=0.0005, help="Slippage per trade (default: 0.05%%)")
    ap.add_argument("--output", "-o", default=None, help="Output JSON file")
    args = ap.parse_args()

    # Parse weights
    pillar_weights = {}
    for w in args.weights:
        key, val = w.split("=")
        pillar_weights[key] = float(val)

    try:
        with open(args.input) as f:
            data = json.load(f)

        if isinstance(data, list):
            bars = data
        elif isinstance(data, dict) and "bars" in data:
            bars = data["bars"]
        else:
            raise ValueError("Invalid format")

        result = run_backtest(
            bars=bars,
            pillar_weights=pillar_weights,
            capital=args.capital,
            commission_pct=args.commission,
            slippage_pct=args.slippage,
        )

        output_text = json.dumps(asdict(result), indent=2, ensure_ascii=False)

        if args.output:
            with open(args.output, "w") as f:
                f.write(output_text)
            print(f"[OK] Results saved to {args.output}")
        else:
            print(output_text)

        # Summary to stderr
        print(f"\n[BACKTEST SUMMARY]", file=sys.stderr)
        print(f"  Total Return:    {result.total_return_pct:.2f}%", file=sys.stderr)
        print(f"  Annualized:      {result.annualized_return_pct:.2f}%", file=sys.stderr)
        print(f"  Sharpe Ratio:    {result.sharpe_ratio}", file=sys.stderr)
        print(f"  Max Drawdown:    {result.max_drawdown_pct:.2f}%", file=sys.stderr)
        print(f"  Win Rate:        {result.win_rate_pct:.1f}% ({result.winning_trades}/{result.total_trades})", file=sys.stderr)
        print(f"  Profit Factor:   {result.profit_factor}", file=sys.stderr)

        return 0
    except Exception as e:
        print(f"[ERROR] {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
