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
  'weight_optimizer.simulate_portfolio: on entry `position_size = capital*0.95/price` but `capital` is never reduced by the deployed amount, and on exit `capital = position_size*price` recovers only the 95% invested — the 5% cash sleeve is silently dropped and the entry bar shows a fake ~-5% return. Track cash and position value together so equity = cash + position_size*price on every bar; otherwise the optimizer optimizes against a corrupted equity curve.',
  "trade_plan.generate_trade_plan: `is_short_entry` is hardcoded `False`, so the entire `direction=='short'` branch in calculate_targets/calculate_position_size is unreachable, untested dead code. Either wire short entries through from `decision['action']`, or delete the short branches until they're actually driven.",
  'Split into focused single-concern PRs (scoring_engine, trade_plan, weight_optimizer, data-quality/cache+tests) so each is independently reviewable and revertible — the 28-file bundle is the primary structural blocker.'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
