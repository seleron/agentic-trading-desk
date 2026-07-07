# Address Claude review on PR #3 (rounds 1–0)

## Required fixes:
- Fix the failing independent unittest gate: run the full restored suite (scripts.test_pipeline scripts.test_data_quality scripts.test_scoring_engine)
- find which test breaks — the new gate command in pr-review.sh also contains a literal '\\n' in a printf/log line that likely breaks the script itself — and repair the code
- not the tests.
- BOT
- 'Revert or justify the pr-review-poll.sh change that removed select(.headRefName == "autonomous/scaffolding"): as written the poller now dispatches reviews for ALL open PRs — an unintended behavior change; if intended it belongs in its own reviewed PR.'
- BOT\\\\
- Clean up or drop the unrelated/malformed backlog files: 008-fix-pr2.md rewrite and new 009-fix-pr2.md contain truncated fixes lists ('rounds 1–0'
- a stray '7/8'
- an unterminated bullet) that are unrelated to the scoring change.
