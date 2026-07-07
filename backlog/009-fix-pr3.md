# Address Claude review on PR #3 (rounds 1–0)

## Required fixes:
- 'Fix the failing independent unittest gate: run the full restored suite locally
- identify which test breaks (likely a pre-existing scoring/orchestrator test affected by the weight rebalance or the new pivot_risk component)
- and repair the code — do NOT weaken or delete the failing test to make it pass.'
- BOT
- 'Revert or justify the pr-review-poll.sh change that removed `select(.headRefName == "autonomous/scaffolding")` — as written the poller now dispatches reviews for ALL open PRs
- which is an unintended scope/behavior change; if intended
- it belongs in its own reviewed PR.'
- Reconcile the backlog docs: 009-fix-pr2.md contains a malformed/truncated fixes list ('rounds 1–0'
- a stray '7/8'
- an unterminated bullet) — clean it up or drop it from this PR since it is unrelated to the scoring change.
