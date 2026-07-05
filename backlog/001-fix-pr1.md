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
  'weight_optimizer.simulate_portfolio: track cash and position value separately so equity = cash + position_size*price on every bar. On entry, move deployed cash out of `capital` (cash -= position_size*price); on the entry bar equity must NOT drop by the 5% cash sleeve. On exit, return the position value to cash. This removes the phantom -5% entry-bar return that corrupts daily_returns and the Sharpe ratio.',
  "trade_plan.generate_trade_plan: `is_short_entry` is hardcoded False, making the entire direction=='short' path in calculate_targets/calculate_position_size unreachable dead code. Either wire short entries from decision['action'], or delete the short branches until they are actually driven.",
  'Split into focused single-concern PRs (scoring_engine, trade_plan, weight_optimizer, data-quality/cache+tests). The 28-file/4-concern bundle is a structural blocker to independent review and revert.'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
