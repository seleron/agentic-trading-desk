---
rank: 0
title: Address Claude review on PR #9
area: review-fix
---
# Address Claude review on PR #9
PR: #9
Branch: auto/daily-validation-tracker
Resolves-Backlog: 027-daily-validation-tracker 007-fix-pr9

## Why
Claude Opus 4.8 requested changes on PR #9 (round 4).

## Required fixes
- Revert the metrics/baseline.json change: a standalone validation_tracker.py has no legitimate reason to touch the gate/metrics baseline. If a change is genuinely needed, state why in the PR; otherwise remove it (scope creep / gate-baseline edit).
- Google Sheets write is non-functional as written: _append_to_google_sheet passes only an API key, but Sheets API v4 append requires OAuth2/service-account auth (your own _get_google_sheet_id docstring admits this), so any real write returns 401. Either implement service-account auth or remove the Sheets integration and its passing-mock tests rather than shipping a stub that always falls back.
- _get_morning_closes/_get_eod_closes ignore target_date entirely (they always pull period='5d'/'1mo' relative to 'now'), so running --mode morning/eod --date <past date> silently records today's prices under a historical date. Fetch by explicit start/end date range, or hard-guard the script to reject a --date that isn't today so backtest misuse can't corrupt the DB.

## Acceptance
- Trusted gate passes: `bash scripts/ci.sh` prints GATE PASSED
- Every fix above is addressed in the diff; no regressions
- Re-review approves

## Constraints
- UPDATE the existing branch `auto/daily-validation-tracker` (do NOT open a new PR)
- Do NOT edit scripts/ci.sh, metrics/baseline.json, or test files to force a pass
