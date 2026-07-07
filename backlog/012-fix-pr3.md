# Address Claude review on PR #3 (rounds 1–0)

## Required fixes:
- 'Fix the broken line in scripts/hermes/pr-review.sh: the `git -C "$WT" checkout ... 2>/dev/null` line was split by a literal newline into `2>/` + newline + `v/null`
- which is invalid shell and will break the gate script. Restore it to a single `2>/dev/null`.'
- Remove accidental committed artifacts that don't belong to this change: the empty `ema20` and `ema50` files
- the `.hermes/pr2-body.md` draft
- and the `agentic-trading-review-2` gitlink/submodule (commit 8b7666a) which looks like a stray review worktree checked in by mistake.
- BOT
- 'Revert or justify the pr-review-poll.sh change that dropped `select(.headRefName == "autonomous/scaffolding")` — as written the poller now dispatches reviews for ALL open PRs
- an unintended behavior change that belongs in its own reviewed PR.'
- BOT\\
- Drop the unrelated and malformed backlog files added here (009-fix-pr2.md
- 009-fix-pr3.md with 'rounds 1–0'
- stray '7/8'
- bare 'BOT'/'7/8' lines and unterminated bullets); the proposed/007-010 backlog items are also unrelated scope and should not ride along with the scoring change.
