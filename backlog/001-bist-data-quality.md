---
rank: 1
title: BIST data quality improvements — retries, cache, gap handling
area: data
depends_on:
---

## Why

`fetch_bist_data()` in `data_fetcher.py` has basic error handling but no retry logic, local cache, or OHLCV gap detection. On exchange downtime (common for BIST), a single failed request kills the entire scan. Also need to handle missing data points gracefully — indicators fail with NaN on gaps.

## Acceptance Criteria

- [ ] Retry up to 3x with exponential backoff on connection errors
- [ ] Local JSON cache per ticker+timeframe with configurable TTL (default: 5 min)
- [ ] Gap detection: log warnings when OHLCV has >1 day gap between bars
- [ ] NaN-safe indicators: forward-fill gaps up to N bars, then flag as "data quality warning" in output
- [ ] All existing tests pass

## Constraints

- Cache lives in `~/.cache/agentic-trading-desk/` (not repo)
- Retry backoff: 1s, 3s, 9s max
- Must not change the public API of `fetch_bist_data()` or `fetch_data()`

## Notes

- Current implementation uses ccxt's `fetch_ohlcv()` directly — wrap in retry decorator
- Look at Adverts-Project's scrape retry patterns for inspiration
- Indicators that fail on NaN: EMA slope calculation, TRIX
