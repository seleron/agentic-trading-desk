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
Claude Opus 4.8 requested changes on PR #9 (round 2).

## Required fixes
- EOD mode in main(): `records` is only assigned inside the `if not eod_prices:` fallback branch, so the normal path (yfinance returns data) hits `print(json.dumps(records))` with `records` unbound → NameError, and the real `eod_prices` are never passed to `record_eod_actuals`. Fix so the happy path calls `record_eod_actuals(args.date, eod_prices, args.db)`.
- Make morning vs EOD use genuinely different prices: `_get_eod_closes` currently returns the same candle as `_get_morning_closes` (both `hist.iloc[-1]` Close), so delta is structurally always 0 and correctness is meaningless. Fetch the morning reference (e.g. prior close / open) distinctly from the EOD close, or document/compute delta from open→close of the trading day.
- Replace the stubbed `simulated_score = 50.0 + (close_price % 10) * 2` in morning mode with real integration to scoring_engine.py; as written the tracker validates a deterministic pseudo-score, not the engine's actual predictions, so it measures nothing useful.
- Remove or clearly gate the Google Sheets path: create-spreadsheet and values:append via a bare `?key=API_KEY` is not permitted by Sheets API v4 for writes (needs OAuth2/service account), so `write_to_google_sheets` will always fail in practice — either drop it or wire proper auth rather than shipping a non-functional integration.

## Acceptance
- Trusted gate passes: `bash scripts/ci.sh` prints GATE PASSED
- Every fix above is addressed in the diff; no regressions
- Re-review approves

## Constraints
- UPDATE the existing branch `auto/daily-validation-tracker` (do NOT open a new PR)
- Do NOT edit scripts/ci.sh, metrics/baseline.json, or test files to force a pass
