---
rank: 4
title: Additional technical indicators — Ichimoku, VWAP, ATR
area: indicators
depends_on:
---

## Why

Current scoring engine uses EMA, RSI, MACD, TRIX, Bollinger. Missing key indicators that traders rely on for confirmation:

- **Ichimoku Cloud** (trend direction + support/resistance) — very popular in Asian/BIST markets
- **VWAP** (volume-weighted average price) — critical for intraday mean reversion signals  
- **ATR** (average true range) — better volatility measure than Bollinger width alone; essential for dynamic stop-loss placement

## Acceptance Criteria

- [ ] `scripts/indicators.py` gains new functions: `calculate_ichimoku()`, `calculate_vwap()`, `calculate_atr()`
- [ ] Ichimoku returns cloud components (tenkan, kijun, senkou span A/B) as structured dict
- [ ] VWAP calculated from session data (requires intraday data or daily approximation)
- [ ] ATR used by trade_plan.py for dynamic stop-loss distance (ATR * multiplier)
- [ ] New scoring component: "Ichimoku alignment" (+5 to +10 score if price above cloud + TK cross bullish)
- [ ] All new indicators have unit tests in existing test suite

## Constraints

- Ichimoku needs 74+ bars minimum — handle gracefully for tickers with short history
- VWAP on daily data is just a running average (not true session VWAP) — note this limitation
- ATR period: default 14 (standard), configurable in config.yaml
- Must not break existing indicator outputs or API

## Notes

- Ichimoku implementation: use pandas rolling + shift operations, no external library needed
- Adverts-Project uses pygount for code metrics — similar approach: keep new code self-contained
- Consider adding these to the scoring engine's "7 components" as a sub-component rather than separate pillar
