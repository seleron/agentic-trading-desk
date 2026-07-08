# Address Claude review on PR #3
\
Area: review-fix
\
Rank: 1
\
PR: #3
\
Branch: autonomous/scaffolding
\
Base Branch: main
\
Resolves-Backlog: fix-pr3
\
Claude-Round: 1
\

\
## Why
\
Claude Opus 4.8 requested changes on PR #3 (round 1).
\

\
## Required fixes
\
- ["Restore the independent gate to PASS: run the full unittest suite against the base harness and fix whatever regressed (e.g. the removed test_run_backtest_requires_pillar_weights contract) — do not weaken or skip tests to make it green."
- "Split into one concern per PR: land pivot_risk scoring alone (scoring_engine.py weight rebalance + test_scoring_engine.py + test_data_quality.py pivot tests + orchestrator r2/s2 rounding). Move the admin correction integration
-  portfolio position tracker
-  run_intraday_loop scanner
-  backtest Optional-weights change
-  and notification_router Telegram integration into their own separately-reviewed PRs."
- "Resolve the yfinance premise: orchestrator.py's backtest fallback does an unguarded `import yfinance as _yf` that raises ImportError whenever ccxt returns <200 bars
-  but yfinance is not in requirements.txt — either add yfinance to requirements.txt or drop the fallback and degrade safely (skip the symbol) using only fetch_bist_data."
- "Wire telegram_config through the intraday alert path: run_intraday_loop calls route_notifications() without telegram_config/trade_plans/trades_report
-  so intraday alerts never actually send Telegram — thread the same config main() loads."
- "Drop the incidental orchestrator.py churn unrelated to scoring (Step 3/Step 4 comment relabeling
-  output dict key reordering) — it is review noise."]
\

\
## Acceptance
\
- Unit tests pass (run: python3 -m unittest scripts.test_pipeline scripts.test_data_quality scripts.test_scoring_engine)
\
- All fixes from Claude review are addressed in the diff
\
- No regressions to existing functionality
\

\
## Constraints
\
- UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR)
\
- Do not edit test_data_quality.py — restore from base if needed for gate
\
- Push commits with descriptive messages matching fix keywords (helps Claude fix-awareness)
