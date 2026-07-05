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
  'Split into focused, single-concern PRs (scoring_engine, trade_plan, weight_optimizer, data-quality/cache+tests) so each is independently reviewable and revertible — this bundling is the primary blocker.',
  'Confirm orchestrator.py actually binds the name used at runtime (e.g. `from datetime import date as date_type` for `date_type.today()`); an unbound name will crash the pipeline summary and it is not shown in the diff.',
  'Confirm data_fetcher.py truly exports _retry_with_backoff, detect_gaps, forward_fill, _cache_dir/_cache_key/get_cached_data/save_cached_data with the exact signatures test_data_quality.py assumes (retries=, backoffs=, retryable_exceptions=, ttl_seconds=, max_gap=, max_gap_seconds=), and that forward_fill lives where indicators.py imports it from — these definitions are outside the shown diff.',
  "In trade_plan.generate_trade_plan, is_short_entry is hardcoded False so the entire `direction=='short'` path in calculate_targets/calculate_position_size is dead; either wire short entries through from the decision or drop the unreachable branch to avoid untested code."
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
