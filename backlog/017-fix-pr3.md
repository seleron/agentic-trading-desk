# Address Claude review on PR #3
Area: review-fix
Rank: 1
PR: #
%s
Branch: autonomous/scaffolding
Resolves-Backlog: 017-fix-pr3

## Why
Claude Opus 4.8 requested changes on PR #3 (round 1).

## Required fixes
["Remove accidental artifacts that don't belong to this change: the empty top-level `ema20` and `ema50` files, `.hermes/pr2-body.md`, and the stray `agentic-trading-review-2` gitlink/submodule (commit 8b7666a) which is a review-worktree leftover checked in by mistake.","Split into one concern per PR: land pivot_risk scoring alone (scoring_engine.py weight rebalance + test_scoring_engine.py + test_data_quality.py pivot tests + orchestrator r2/s2 population); move the MTF orchestrator wiring, the backtest.py Optional-weights change + orchestrator backtest step, and the hermes changes (pr-review.sh [BOT] rename / get() JSON.stringify / gate grep / pr-review-poll.sh filter, pytest.ini) into their own reviewed PRs.","Resolve the yfinance premise: the orchestrator backtest block still does an unguarded runtime `import yfinance as _yf` in the fallback path, but yfinance is not in requirements.txt — either declare it or source history solely from the existing ccxt fetch_bist_data path so the pipeline degrades safely instead of raising.","Fix the indentation regressions introduced in orchestrator.py: the `# Step 3:` comment sits at 3 spaces and the `\"mtf_verification\"` dict key at 7 spaces — align both to the surrounding block.","Reconcile/clean the backlog churn: 008-fix-pr2.md, 009-fix-pr2.md, 009-fix-pr3.md, 009-pr2-scope-merge.md and pr2-cleanup-done.md duplicate and contradict each other (malformed 'rounds 1–0' headers, stale plan claiming MTF/backtest delivered) — collapse them to reflect what this PR actually ships.","Justify or move the pr-review-poll.sh change independently: aside from the [BOT] regex escape it now keys dedup off the whole PR list — confirm the `select(.headRefName == \"autonomous/scaffolding\")` branch filter is still enforced so the poller doesn't dispatch reviews for all open PRs."]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
