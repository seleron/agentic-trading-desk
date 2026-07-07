# Address Claude review on PR #3
Area: review-fix
Rank: 1
PR: #
%s
Branch: autonomous/scaffolding
Resolves-Backlog: 016-fix-pr3

## Why
Claude Opus 4.8 requested changes on PR #3 (round 1).

## Required fixes
["Remove the accidental artifacts that don't belong to this change: the empty `ema20` and `ema50` files, `.hermes/pr2-body.md`, and the stray `agentic-trading-review-2` gitlink/submodule (commit 8b7666a) — these are review-worktree/scratch leftovers checked in by mistake.","Split into one concern per PR as repeatedly requested: land pivot_risk scoring + the weight rebalance (scoring_engine.py, test_scoring_engine.py, test_data_quality.py pivot tests) alone; move the orchestrator MTF wiring, the backtest.py Optional-pillar-weights change + orchestrator backtest step, and the hermes script changes (pr-review.sh [BOT] rename / get() JSON.stringify / python3 split, pr-review-poll.sh, pytest.ini) into their own reviewed PRs.","Resolve the yfinance premise per owner guidance: the orchestrator backtest step still does a runtime `import yfinance` as a fallback but yfinance is not in requirements.txt — either declare it or drop the fallback and rely solely on the existing ccxt `fetch_bist_data` path, so the block doesn't silently degrade inside its except handler.","Fix the sloppy indentation introduced in orchestrator.py: the `# Step 3:` comment is at 3 spaces and the `\"mtf_verification\"` dict key at 7 spaces (they compile only because they sit inside brackets, but they're inconsistent with the surrounding block).","Clean up and reconcile the backlog/plan churn: the malformed `009-fix-pr2.md` (\"rounds 1–0\", stray \"7/8\", unterminated bullet) and `009-fix-pr3.md`, plus the duplicated `008-fix-pr2.md`/`pr2-cleanup-done.md`, and the plan doc that still lists MTF/backtest tasks as delivered — reconcile them with what this PR actually ships or drop them."]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
