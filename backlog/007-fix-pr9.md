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
Claude Opus 4.8 requested changes on PR #9 (round 3).

## Required fixes
- Replace the direct `import yfinance as yf` fetch helpers (_get_morning_closes/_get_eod_closes) with the repo's current BIST provider (borsapy / the unified data provider) so the tracker actually fetches data via the supported path — yfinance may no longer be an installed dependency after commit 145df28.
- Fix the morning-vs-EOD reference mismatch: both helpers take `hist.iloc[-1]` of a 5d window, so morning_close and eod_close resolve to the same/intraday candle and delta_pct is not a genuine prediction-window return. Morning must capture the reference price and EOD the later actual close so the delta and CORRECT/INCORRECT flags mean what the docstrings claim.
- Fix or remove the Google Sheets export: `_append_to_google_sheet` uses `values:...:append?key={api_key}` which Sheets API v4 does not permit for writes (as the `_get_google_sheet_id` docstring itself states) — implement service-account/OAuth2 auth or drop the non-functional write path rather than shipping a stub that can never succeed.

## Acceptance
- Trusted gate passes: `bash scripts/ci.sh` prints GATE PASSED
- Every fix above is addressed in the diff; no regressions
- Re-review approves

## Constraints
- UPDATE the existing branch `auto/daily-validation-tracker` (do NOT open a new PR)
- Do NOT edit scripts/ci.sh, metrics/baseline.json, or test files to force a pass
