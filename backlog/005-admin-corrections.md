---
rank: 3
title: Admin correction system for manual overrides
area: feedback-loop
depends_on:
---

## Why

Like Adverts-Project's admin corrections, the trading engine should accept manual overrides — e.g., "THYAO is actually bullish despite bearish score" or "exclude X stock from scan today." Without this, false signals can't be corrected and the learning module has no ground truth.

## Acceptance Criteria

- [ ] New config section `[admin_corrections]` in config.yaml with per-ticker overrides
- [ ] Override types: `force_buy`, `force_sell`, `ignore`, `custom_weight_modifier`
- [ ] Scoring engine checks admin corrections before returning final decision
- [ ] Corrections logged to SQLite for learning module analysis
- [ ] CLI command to add/remove corrections without editing YAML

## Constraints

- Admin overrides are additive — they don't replace scoring, just adjust the final decision
- `ignore` type: skip ticker entirely from selection (same as current hardcoded excludes)
- Format in config.yaml should be human-editable with comments

## Notes

- Adverts-Project admin corrections store user corrections and feed them back to LLM → future: same pattern for trading engine
- Consider a simple JSON file at `~/.config/agentic-trading-desk/corrections.json` as an alternative to config.yaml edits
