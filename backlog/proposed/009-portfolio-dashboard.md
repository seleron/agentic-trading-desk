---
rank: 9
title: portfolio-dashboard
area: ux_reporting
depends_on: [004]
---

## Why

The existing `eod_module.py` records individual trades (entry, exit, PnL) in SQLite but provides **no portfolio-level view**. After running several scans and executing trades, the user has to query the raw database to understand their overall picture. None of the comparable projects include this — they're scanner-focused and leave portfolio tracking to external tools like Robinhood's UI or brokerage dashboards.

For an autonomous desk that executes ~2 top picks per day on a T+1 cash account, knowing:
- Total unrealized PnL across all open positions
- Sector allocation (how much is in energy vs banking vs tech)
- Win rate by indicator configuration (did the ATR-based stops actually improve outcomes?)
- Days since last profitable trade

...is essential for the learning module to make informed weight adjustments. The current `learning_module.py` just counts trades and adjusts weights blindly; without portfolio context, it can't distinguish "good signals on bad execution" from "bad signals."

Additionally, **borsapy** provides sector classification data (energy, banking, technology, etc.) for BIST stocks — we should leverage this to build a sector allocation view.

## Acceptance Criteria
- [ ] New script `scripts/portfolio.py` with CLI interface:
  - `portfolio.py --status` → prints current portfolio summary (positions, unrealized PnL, total value)
  - `portfolio.py --history --days 30` → prints daily PnL history for the last N days
  - `portfolio.py --sector-allocation` → breakdown of positions by BIST sector
- [ ] SQLite schema extended in `eod_module.py` to maintain:
  - A `positions` table tracking open orders (symbol, shares, entry_price, date)
  - A `portfolio_snapshots` table recording daily portfolio state (total_value, unrealized_pnl, cash_balance) for charting/historical analysis
- [ ] `orchestrator.py` calls a new `update_portfolio()` function at the end of each pipeline run to:
  - Close positions that have been held past their target date
  - Record daily snapshot if any trade was executed or closed
- [ ] `portfolio.py --performance-attribution` → shows which scoring components (trend, momentum, volume, etc.) correlate most strongly with profitable outcomes — feeds directly back into the learning module. Uses Pearson correlation on historical component scores vs. realized PnL per trade.
- [ ] All portfolio queries use parameterized SQLite statements to prevent SQL injection.

## Constraints
- Must work with existing `data/trades.db` schema — no migration required for pre-existing data. New tables are additive only.
- Sector data sourced from borsapy (`borsapy.get_stock_info(symbol).sector`) or a local CSV mapping if borsapy is unavailable.
- Portfolio view should be text-only (no web UI) to match the project's "terminal-first" design philosophy.

## Notes
- The `portfolio_snapshots` table enables future charting with matplotlib/plotly — but charting itself is out of scope for this item.
- Consider adding a **dry-run mode** where portfolio tracks "paper trades" without affecting real cash balance — useful for testing new weight combinations.
