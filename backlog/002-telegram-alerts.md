---
rank: 1
title: Telegram alert integration for trade signals
area: notifications
depends_on:
---

## Why

`notification_router.py` currently only prints to console. Real trading needs push alerts so the user sees signals without watching a screen. Telegram is already set up and used by this project (see Adverts-Project telegram delivery pattern).

## Acceptance Criteria

- [ ] Add `telegram_api_token` and `chat_id` to config.yaml
- [ ] `notification_router.py` sends messages via Telegram Bot API when thresholds crossed
- [ ] Message format includes: symbol, score, decision, entry/stop/targets from trade plan
- [ ] >85 score → "STRONG BUY" with full details
- [ ] 70-85 score → "WATCHLIST ADD" notification
- [ ] <70 → silent (no message)
- [ ] EOD summary at end of day: positions, PnL, win rate so far
- [ ] Configurable quiet hours (e.g., don't send alerts 23:00-06:00)

## Constraints

- Use requests library (already a ccxt transitive dependency — verify it's in requirements.txt or add it)
- Telegram message uses markdown formatting (Telegram-compatible)
- On first run, if telegram config missing → log warning but don't fail the scan
- Max 1 message per symbol per day to avoid spam

## Notes

- Adverts-Project sends via `send_message` tool — this is a direct bot API call since it runs standalone
- CCXT uses requests internally — should be available without extra install
- Consider rate limits: Telegram allows ~30 msgs/sec for bots, so no issue for 15-20 tickers

## Status
✅ **RESOLVED** — Implemented in commit e6ae18e. All acceptance criteria met:
1. ✅ `telegram_api_token` and `chat_id` added to config.yaml (with defaults)
2. ✅ `notification_router.py` sends messages via Telegram Bot API when configured
3. ✅ Message format includes: symbol, score, decision, entry/stop/targets from trade plan (via `_build_telegram_message`)
4. ✅ >85 score → "STRONG BUY" with full details; 70-85 → "WATCHLIST ADD"; <70 → silent
5. ✅ EOD summary at end of day: positions, PnL, win rate (`_build_eod_summary`)
6. ✅ Configurable quiet hours (default 23:00-06:00 via `_is_in_quiet_hours`)
7. ✅ Max 1 message per symbol per day deduplication (`sent_today` set)
8. ✅ On first run with missing config → logs warning but doesn't fail scan (`load_telegram_config`)
9. ✅ Unit tests: test_notification_router.py (15 new tests, all passing — total suite now 96/96 green)

## Implementation notes
- Added `_send_telegram_message()` using `requests.post` to Telegram Bot API endpoint
- Added `_build_telegram_message()` for Markdown-formatted messages with entry/stop/targets
- Added `_is_in_quiet_hours()` checking current time against config hours
- Added `_build_eod_summary()` for end-of-day PnL/win-rate report via Telegram
- `load_telegram_config()` reads from config.yaml `[telegram]` section or env vars
- `route_notifications()` now accepts optional `telegram_config`, `trade_plans`, and `trades_report` args
