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
  "scoring_engine.compute_trend_score ignores ema200 and can only award 15 (+5 partial), so the documented Trend max of 25 and the 'EMA50>EMA200 → +10' rule are unreachable — wire in the ema200 credit (and the close-above-both bonus) or correct the docstring/COMPONENT_WEIGHTS so score math matches spec.",
  "score_quote sets volume_avg_20 default to volume*1.5 when missing; this forces compute_volume_score to 0 (volume >= 1.5*volume is always false) AND suppresses the low-volume penalty (volume < 0.6*1.5*volume is always false), silently zeroing the volume pillar. Require volume_avg_20 or skip both the volume component and penalty explicitly when it's absent.",
  'Verify orchestrator.py imports the name used at runtime — `date_type.today()` needs an explicit `from datetime import date as date_type` (not shown in the truncated diff); an unbound name will crash the pipeline summary.',
  'Confirm data_fetcher actually exports _retry_with_backoff, detect_gaps, forward_fill, _cache_dir/_cache_key/get_cached_data/save_cached_data with the exact signatures test_data_quality.py assumes (retries=, backoffs=, retryable_exceptions=, ttl_seconds=, max_gap_seconds=/max_gap=), since those definitions are outside the shown diff.',
  'Split into focused, one-concern PRs (scoring, trade_plan, weight_optimizer, data-quality/cache) to keep review and revert tractable.'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
