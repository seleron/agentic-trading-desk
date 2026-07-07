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
- ["Resolve the yfinance premise: orchestrator.py's backtest fallback does an unguarded `import yfinance as _yf` (raising ImportError at runtime whenever ccxt returns <200 bars)
-  but yfinance is not in requirements.txt — either add yfinance to requirements.txt or drop the fallback and degrade safely (skip the symbol) using only the ccxt fetch_bist_data path."
- "Split into one concern per PR: land pivot_risk scoring alone (scoring_engine.py weight rebalance + test_scoring_engine.py + test_data_quality.py pivot tests + orchestrator r2/s2 rounding); move the intraday run_intraday_loop scanner
-  the backtest.py Optional-weights change
-  and the notification_router Telegram integration into their own separately-reviewed PRs."
- "Reconcile the incidental orchestrator.py churn unrelated to scoring: the `# Step 3`/`# Step 4` comment relabeling and the reordering of output dict keys (mtf_verification/backtest_results/eod_report) is noise — drop it or keep it consistent."
- "Confirm the intraday alert path re-routes notifications with the same telegram_config/trade_plans as the single-pass main() — currently run_intraday_loop calls route_notifications(curr_scores_output
-  curr_selection) with no telegram_config
-  so intraday alerts will never actually reach Telegram; wire the config through or document that this is intentional."]
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
