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
