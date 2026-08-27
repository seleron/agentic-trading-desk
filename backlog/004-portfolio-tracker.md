---
rank: 2
title: Portfolio position tracker module
area: portfolio
depends_on:
---

## Why

The EOD module tracks daily PnL but doesn't track individual positions, average entry prices, unrealized gains/losses, or position sizing. A proper position tracker bridges scanning and execution.

## Acceptance Criteria

- [x] New module `scripts/portfolio.py` with SQLite-backed state
- [x] Tracks: symbol, entry_price, quantity, avg_cost, current_pnl, unrealized_pnl_pct
- [x] Integrates with trade_plan.py output — can auto-create positions from approved plans
- [x] Supports partial fills and position scaling (add/reduce)
- [x] Daily report includes per-position PnL + portfolio-level summary
- [x] Configurable max position size (% of total capital)

## ✅ RESOLVED — Implemented 2026-07-08

## Constraints

- SQLite DB at `~/.local/share/agentic-trading-desk/portfolio.db`
- Non-blocking: scanner should not fail if portfolio module is unavailable
- Position states: OPEN, CLOSED (realized), PENDING (awaiting execution)

## Notes

- EOD module already uses SQLite — consider consolidating into one DB or keeping separate
- Can build on existing `eod_module.py` patterns for database interface
- Future: integrate with broker API (ccxt supports BIST via some exchanges)
