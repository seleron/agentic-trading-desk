# Address Claude review on PR #3
Area: review-fix
Rank: 1
PR: #
%s
Branch: autonomous/scaffolding
Resolves-Backlog: 014-fix-pr3

## Why
Claude Opus 4.8 requested changes on PR #3 (round 1).

## Required fixes
["Fix the failing independent gate: run the full restored suite (scripts.test_pipeline scripts.test_data_quality scripts.test_scoring_engine) locally, find which test actually breaks, and repair the code — do not weaken or delete tests. The new gate command in pr-review.sh must be verified to run cleanly (no literal newline splits).","Remove accidental artifacts that don't belong to this change: the empty ema20 and ema50 files, .hermes/pr2-body.md, and the agentic-trading-review-2 gitlink/submodule (commit 8b7666a) which is a stray review worktree checked in by mistake.","Split into one concern per PR: land pivot_risk scoring (scoring_engine.py + test_scoring_engine.py + orchestrator r2/s2 population) alone; move the hermes [BOT] marker rename across pr-review.sh / pr-review-dispatch.sh / pr-review-poll.sh into its own PR; move backtest.py signature change and orchestrator MTF/backtest wiring out too.","Revert or justify the pr-review-poll.sh change that dropped select(.headRefName == \"autonomous/scaffolding\"): as written the poller now dispatches reviews for ALL open PRs, an unintended behavior change that belongs in its own reviewed PR.","Escape the [BOT] marker inside jq test(...) regex filters in pr-review-poll.sh and pr-review.sh: [BOT] is a regex character class matching any of B/O/T, so it mis-matches older comments and breaks NEEDS_HUMAN dedup and round counting — match a literal (e.g. \\[BOT\\] or a fixed-string test).","Clean up or drop the malformed backlog files (009-fix-pr2.md, 009-fix-pr3.md): they contain truncated/unterminated fixes lists ('rounds 1–0', stray '7/8', 'BOT', unterminated bullets) unrelated to the scoring change."]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
