# Fix PR #3 Claude review — split concerns, yfinance import, orchestrator noise
Area: review-fix
Rank: 0
PR: #3
Branch: autonomous/scaffolding

## Why
Claude Opus 4.8 requested changes on PR #3 (round 1). The PR is too large with multiple unrelated concerns and carries an unguarded `import yfinance as _yf` not in requirements.txt.

## Required fixes

### 1. Split into one concern per PR
- **pivot_risk scoring alone**: scoring_engine.py weight rebalance + test_scoring_engine.py + test_data_quality.py pivot tests + orchestrator r2/s2 rounding
- Move to separate PRs: notification_router Telegram integration, new run_intraday_loop/_should_alert/_is_in_quiet_hours orchestrator additions, backtest Optional-weights change, hermes/pr-review-poll edits

### 2. Fix unguarded yfinance import in orchestrator.py
The backtest fallback still does `import yfinance as _yf` but yfinance is not in requirements.txt. Either:
- Declare it as a dependency (add to requirements.txt), OR
- Source history solely from the existing ccxt fetch_bist_data path so the pipeline degrades safely (warn + continue) instead of raising ImportError at runtime

### 3. Drop incidental orchestrator noise unrelated to scoring
The `# Step 3:`/`# Step 4:` comment relabeling and reordering of output-dict keys (mtf_verification/backtest_results/eod_report) are churn that inflates the diff — revert or move to their own PR.

### 4. Confirm pr-review-poll.sh branch filter
Ensure `select(.headRefName == "autonomous/scaffolding")` is still enforced so the poller does not dispatch reviews for all open PRs.

## Acceptance
- Unit tests pass (run: python3 -m unittest scripts.test_pipeline scripts.test_data_quality scripts.test_scoring_engine)
- All fixes from Claude review are addressed in the diff
- No regressions to existing functionality

## Constraints
- UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR)
- Do not edit test_data_quality.py — restore from base if needed for gate
- Push commits with descriptive messages matching fix keywords (helps Claude fix-awareness)
