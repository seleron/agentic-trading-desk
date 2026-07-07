# Address Claude review on PR #2
Area: review-fix
Rank: 1
PR: #2
Branch: feature/pivot-mtf-backtest-integration
Resolves-Backlog: 008-fix-pr2

## Why
Claude Opus 4.8 requested changes on PR #2 (round 1).

## Required fixes
[
  'Fix the independent unittest gate — it currently FAILS on this branch; restore/repair whatever test is broken rather than weakening it, and confirm the full suite passes before re-review.',
  "Populate quote['r2']/['s2'] in the orchestrator pivot block (plan Task 1) so compute_pivot_risk_score's 'below R2' +2 branch can actually fire; otherwise it is dead code and pivot_risk caps at 3/5 in practice.",
  'Add a scoring test that exercises the r2/s2 branch of compute_pivot_risk_score to prove the +2 continuation path works.',
  'Reconcile the PR/plan with the diff: only pivot_risk scoring is delivered. Remove the MTF (Task 3) and backtest.py upgrade (Tasks 4-5) claims and their unchecked plan tasks from this PR, or deliver and smoke-test them separately.',
  'Split into one concern per PR — merge pivot_risk scoring on its own; MTF wiring and backtest integration each become separate PRs (and each would need yfinance declared in requirements.txt or, per owner guidance, sourced from existing ccxt ohlcv_data instead of a second undeclared provider).'
]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `feature/pivot-mtf-backtest-integration` (do NOT open a new PR). Do not edit test_data_quality.py.
## Implementation Notes
- **Unittest gate FAILS**: Fixed root cause in `_patch_cache_dir()` — the original code patched `"data_fetcher._cache_dir"` by string path but tests imported `_cache_dir` at module level, so calls like `Path(_cache_dir())` used an unpatched function reference. Fix: patch on module object (`_df_module._cache_dir`) and update local namespace via `globals()['_cache_dir'] = mock`.
- **Indentation**: Fixed under-indented comment in `orchestrator.py` step 4b block.
- **pr-review.sh**: Fixed literal `\n` line-break issue in independent gate runner.
## Status
✅ **RESOLVED** — PR #2 merged July 7, 19:10 UTC. All fixes applied to `feature/pivot-mtf-backtest-integration` before merge.
