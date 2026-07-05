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
  "scoring_engine.compute_trend_score ignores ema200 and only ever awards 15 (+5 partial for bearish), so the documented Trend max of 25, the 'EMA50>EMA200 → +10' rule, and the 'close above both → +10 bonus' are all unreachable. Wire in the ema200 credit and close-above-both bonus, or correct the docstring/COMPONENT_WEIGHTS so the math matches the spec.",
  "score_quote defaults volume_avg_20 to volume*1.5 when the key is missing. That guarantees volume < avg (volume_score forced to 0) AND volume >= 0.6*avg (low-volume penalty never fires), silently zeroing the whole volume component. Require volume_avg_20 explicitly, or record a 'volume data missing' rationale and skip that component instead of fabricating an average.",
  "Verify orchestrator's `date_type` name is actually imported (e.g. `from datetime import date as date_type`) — the import is not in the shown diff and an unbound name would crash the pipeline summary at the point it prints '[PIPELINE COMPLETE]'.",
  'Confirm data_fetcher exports _retry_with_backoff, detect_gaps, _cache_dir/_cache_key/get_cached_data/save_cached_data and indicators.forward_fill with the exact signatures test_data_quality.py assumes (retries=, backoffs=, retryable_exceptions=, ttl_seconds=, max_gap_seconds=, max_gap=). The gate passing implies these exist, but the definitions are outside the truncated diff — confirm before merge.',
  'Split into focused PRs — scoring, trade_plan, weight_optimizer, and data-quality/cache are independent concerns — to keep review and revert tractable (one concern per change).'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
