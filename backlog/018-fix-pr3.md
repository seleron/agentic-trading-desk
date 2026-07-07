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
- ["Remove the empty scratch artifacts committed by mistake: the zero-byte `ema20` and `ema50` files at repo root."
- "Fix pytest.ini: `addopts = --ignore=agentic-trading-review-2` bakes a transient review-worktree path into committed config — drop that ignore (or scope it properly) so the repo doesn't depend on a scratch directory."
- "Resolve the yfinance premise: orchestrator.py still does a runtime `import yfinance as _yf` fallback but yfinance is not in requirements.txt — either declare the dependency or drop the fallback and rely solely on the ccxt `fetch_bist_data` path so the backtest block can't silently fail."
- "Fix the broken indentation in orchestrator.py introduced by this diff: the `# Step 3:` comment sits at 3 spaces and the `\"mtf_verification\"` dict key at 7 spaces — align them with the surrounding block."
- "Split into one concern per PR as requested across prior rounds: land the pivot_risk scoring + weight rebalance (scoring_engine.py
-  test_scoring_engine.py
-  test_data_quality.py pivot tests) alone
-  and move the backtest.py Optional-weights change
-  orchestrator MTF/backtest wiring
-  and the hermes/poll/pytest churn into separate reviewed PRs."]
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
