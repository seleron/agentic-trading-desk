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
- ["Split into one concern per PR: land pivot_risk scoring alone (scoring_engine.py weight rebalance + test_scoring_engine.py + test_data_quality.py pivot tests + orchestrator r2/s2 rounding); move the Telegram notification_router integration
-  the orchestrator backtest/MTF changes
-  and the hermes/pr-review-poll script edits into their own reviewed PRs."
- "Resolve the yfinance premise: the orchestrator backtest fallback still does an unguarded runtime `import yfinance as _yf`
-  but yfinance is not in requirements.txt — either declare it as a dependency or source history solely from the existing ccxt fetch_bist_data path so the pipeline degrades safely instead of raising ImportError."
- "Fix the indentation regressions in orchestrator.py: the `# Step 3:` comment sits at 3 spaces and the `\"mtf_verification\"` dict key at 7 spaces — align both to the surrounding 4-space block."
- "Reconcile the comment/step-label churn in orchestrator.py: the `# Step 3:`/`# Step 4:` relabeling and reordering of the output dict keys is incidental noise unrelated to the scoring change; keep it consistent or drop it."
- "Justify or confirm the pr-review-poll.sh change independently: verify the `select(.headRefName == \"autonomous/scaffolding\")` branch filter is still enforced so the poller doesn't dispatch reviews for all open PRs."]
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
