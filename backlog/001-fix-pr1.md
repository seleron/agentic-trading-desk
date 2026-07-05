# Address Claude review on PR #1
Area: review-fix
Rank: 1
PR: #1
Branch: autonomous/scaffolding
Resolves-Backlog: 001-fix-pr1

## Why
Claude Opus 4.8 requested changes on PR #1 (round 1).

## Required fixes
[
  "trade_plan.generate_trade_plan: is_short_entry is hardcoded to False, so the direction=='short' branches in calculate_targets and calculate_position_size are unreachable dead code. Either wire short entries from decision['action'] (detect SHORT/SELL/EXIT-to-short keywords) or delete the short branches until they are actually driven.",
  'Split the bundle into focused single-concern PRs (scoring_engine, trade_plan, weight_optimizer, data-quality/cache+tests) so each can be reviewed and reverted independently; the 4-concern/35-file scope is a structural blocker to independent review.'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
