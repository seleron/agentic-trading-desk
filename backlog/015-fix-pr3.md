# Address Claude review on PR #3
Area: review-fix
Rank: 1
PR: #
%s
Branch: autonomous/scaffolding
Resolves-Backlog: 015-fix-pr3

## Why
Claude Opus 4.8 requested changes on PR #3 (round 1).

## Required fixes
["Remove accidental artifacts that don't belong to this change: the empty top-level `ema20` and `ema50` files, `.hermes/pr2-body.md`, and the `agentic-trading-review-2` gitlink/submodule (commit 8b7666a) which is a stray review worktree checked in by mistake.","Split into one concern per PR: land pivot_risk scoring alone (scoring_engine.py + test_scoring_engine.py + test_data_quality.py pivot tests + orchestrator r2/s2 population); move the MTF orchestrator wiring, the backtest-in-orchestrator step, the hermes [BOT] marker rename (pr-review.sh/dispatch/poll), and pytest.ini into their own reviewed PRs.","Resolve the yfinance premise per owner guidance: the backtest/MTF orchestrator blocks still import yfinance which is not in requirements.txt — declare it, or source history from the existing ccxt fetch_bist_data path only; today the yfinance fallback silently degrades via except handlers.","Fix the indentation regressions in orchestrator.py introduced here: the `# Step 3:` comment is at 3 spaces and the `\"mtf_verification\"` dict key at 7 spaces — align them to the surrounding block.","Reconcile the backlog/plan churn: the 2026-07-05 plan still lists MTF/backtest tasks as delivered, and 008-fix-pr2.md / 009-fix-pr2.md / 009-fix-pr3.md / pr2-cleanup-done.md / 009-pr2-scope-merge.md duplicate and contradict each other (malformed 'rounds 1–0' lists) — clean them up to reflect what this PR actually ships.","Justify or move the pr-review-poll.sh change that dropped `select(.headRefName == \"autonomous/scaffolding\")`: as written the poller now dispatches reviews for ALL open PRs, a behavior change that belongs in its own reviewed PR."]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
