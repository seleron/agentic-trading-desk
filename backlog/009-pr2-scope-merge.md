# Merge PR #2 concerns into separate branches for review/approval
Area: review-fix
Rank: 1
PR: #2
Branch: feature/pivot-mtf-backtest-integration

## Background
Both manual and cron reviews flagged two blockers preventing merge of `feature/pivot-mtf-backtest-integration`:

### Blocker 1 — Scope creep (one-concern-per-PR rule)
The PR bundles three distinct concerns:
- **pivot_risk scoring** (`scoring_engine.py` + tests)
- **MTF orchestrator wiring** (`orchestrator.py`)  
- **Backtest full-engine integration** (`backtest.py`, `test_pipeline.py`)

### Blocker 2 — Undeclared dependency
Both MTF and backtest paths import `yfinance` at runtime, but it's absent from `requirements.txt`. The live pipeline uses ccxt via `data_fetcher` (yfinance is only needed for the backtest module).

## Fix plan
1. Rebase onto latest main
2. Split into separate branches:
   - `feature/pivot-risk-scoring` — scoring_engine.py + tests only
   - `feature/mtf-orchestrator-wiring` — orchestrator.py MTF integration
   - `feature/backtest-yfinance` — backtest.py + yfinance in requirements.txt (or replace with ccxt)
3. Submit separate PRs targeting main for each concern
