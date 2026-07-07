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
- ["Split into one concern per PR: land pivot_risk scoring alone (scoring_engine.py weight rebalance + test_scoring_engine.py + test_data_quality.py pivot tests + orchestrator r2/s2 rounding). Move the notification_router Telegram integration
-  the new run_intraday_loop/_should_alert/_is_in_quiet_hours orchestrator additions
-  the backtest Optional-weights change
-  and the hermes/pr-review-poll edits into their own separate reviewed PRs."
- "Resolve the yfinance premise in orchestrator.py: the backtest fallback still does an unguarded `import yfinance as _yf` but yfinance is not in requirements.txt — either declare it as a dependency or source history solely from the existing ccxt fetch_bist_data path so the pipeline degrades safely (warn + continue) instead of raising ImportError at runtime."
- "Drop the incidental orchestrator noise unrelated to scoring: the `# Step 3:`/`# Step 4:` comment relabeling and the reordering of output-dict keys (mtf_verification/backtest_results/eod_report) are churn that inflates the diff and should be reverted or moved to their own PR."
- "Confirm the pr-review-poll.sh change still enforces the `select(.headRefName == \"autonomous/scaffolding\")` branch filter so the poller does not dispatch reviews for all open PRs."]
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
