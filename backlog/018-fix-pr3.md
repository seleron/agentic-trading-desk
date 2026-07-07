# Address Claude review on PR #3
Area: review-fix
Rank: 1
PR: #
%s
Branch: autonomous/scaffolding
Resolves-Backlog: fix-pr3 018-fix-pr3

## Why
Claude Opus 4.8 requested changes on PR #3 (round 1).

## Required fixes
["Remove accidental artifacts: the empty top-level `ema20` and `ema50` files, `.hermes/pr2-body.md`, and the stray `agentic-trading-review-2` gitlink/submodule.","Fix pytest.ini: drop the `addopts = --ignore=agentic-trading-review-2` that bakes a transient review-worktree path into committed config.","Resolve the yfinance premise: orchestrator.py's backtest fallback does an unguarded `import yfinance as _yf` but yfinance is not in requirements.txt — either declare the dependency or rely solely on the ccxt `fetch_bist_data` path so the pipeline degrades safely.","Fix orchestrator.py indentation regressions: the `# Step 3:` comment at 3 spaces and the `\"mtf_verification\"` dict key at 7 spaces — realign to the surrounding block.","Split into one concern per PR: land pivot_risk scoring alone (scoring_engine.py rebalance + tests + orchestrator r2/s2 population); move the intraday loop, MTF wiring, backtest.py Optional-weights change, notification_router telegram additions, and hermes/pytest changes into separate reviewed PRs.","Reconcile/clean the contradictory backlog files (008/009-fix-pr2, 009-fix-pr3, 009-pr2-scope-merge, pr2-cleanup-done) so they reflect what this PR actually ships."]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
