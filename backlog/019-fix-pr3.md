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
- ["Remove the zero-byte scratch artifacts ema20 and ema50 at repo root (they are staged for deletion in git status but must actually be gone from the branch)."
- "Resolve the yfinance premise in orchestrator.py: the backtest fallback still does an unguarded runtime `import yfinance as _yf` but yfinance is not in requirements.txt — either declare it as a dependency or drop the fallback and source history solely from the ccxt fetch_bist_data path so the backtest degrades safely instead of raising ImportError."
- "Fix the indentation regressions in orchestrator.py: the `# Step 3:` comment sits at 3 spaces and the `\"mtf_verification\"` dict key at 7 spaces — align both to the surrounding block."
- "Reconcile the incidental comment/step-label churn in orchestrator.py (# Step 3/# Step 4 relabeling and reordering of eod_report/mtf_verification output keys) that is unrelated to the scoring change."
- "Split into one concern per PR as requested across every prior round: land pivot_risk scoring alone (scoring_engine.py weight rebalance + test_scoring_engine.py + test_data_quality.py pivot tests + orchestrator r2/s2 rounding); move the Telegram notification_router integration
-  the new run_intraday_loop
-  and the backtest Optional-weights change into their own reviewed PRs."]
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
