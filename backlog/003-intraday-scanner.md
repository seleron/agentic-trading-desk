---
rank: 2
title: Intraday real-time scanner (not just daily)
area: scanning
depends_on:
---

## Why

Currently the orchestrator runs once per day. BIST stocks can move significantly during the session. An intraday scanner that re-scans every N minutes would catch breakouts and trend changes that happen mid-day.

## Acceptance Criteria

- [ ] Add `intraday_interval_minutes` to config.yaml (default: 60, range: 15-240)
- [ ] Orchestrator loops every N minutes instead of single run
- [ ] Each tick re-runs scoring engine on latest data (calls data_fetcher fresh each time)
- [ ] Only alerts when decision changes (e.g., "NO TRADE" → "BUY") to reduce noise
- [ ] Intraday mode respects quiet hours config
- [ ] Configurable max ticks per run (e.g., 48 = ~12 hours of intraday scanning, then stop)

## Constraints

- Must not break the existing single-run daily mode (use a new `--intraday` CLI flag or config toggle)
- Each tick is independent — no state carried between ticks except latest alert status per symbol
- Memory: don't accumulate OHLCV data across ticks beyond what indicators need

## Notes

- BIST trading hours: 10:00-18:00 TRT (UTC+3) = 07:00-15:00 UTC
- Consider using a simple time-based loop rather than cron for intraday (cron can drift)
- Could use `time.sleep()` in orchestrator with signal handling (SIGTERM for clean exit)

## Status
✅ **RESOLVED** — Implemented in PR #5 (feature/intraday-scanner). All acceptance criteria met:
1. ✅ `intraday_interval_minutes` added to config.yaml `[intraday]` section (default: 60, clamped 15-240)
2. ✅ Orchestrator loops every N minutes via `run_intraday_loop()` with non-blocking sleep
3. ✅ Each tick re-runs full pipeline (`run_full_pipeline`) for fresh scoring engine data
4. ✅ Decision-change detection via `_decision_key()` + `_should_alert()` — only alerts on meaningful changes
5. ✅ Quiet hours respected: Telegram alerts skipped during configured hours (default 23-06)
6. ✅ Configurable `max_ticks` to limit loop duration (None = unlimited); SIGTERM/SIGINT for clean exit
7. ✅ All existing tests pass (109/109 green), plus 13 new intraday-specific unit tests

## Implementation notes
- `_decision_key()` builds a sorted tuple of (symbol, score, action) from selection — enables hashable comparison across ticks
- `_should_alert()` returns True when: first run, decision changed (picks/thresholds differ), or any score shifted ≥ min_score_change
- `_is_in_quiet_hours()` uses module-level `datetime` import for testability via mock.patch
- `run_intraday_loop()` wraps `run_full_pipeline()` in a loop with signal-safe sleep (checks every 5s)
- Default config: enabled=false, interval=60min, max_ticks=null, min_score_change=10 — non-breaking to existing deployments
- Fixed notification_router test that was failing during quiet hours due to unmocked datetime
