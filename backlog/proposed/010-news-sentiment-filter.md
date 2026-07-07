---
rank: 10
title: news-sentiment-filter
area: data_enrichment
depends_on: []
---

## Why

Our pipeline scores stocks purely on technicals (the Three-Pillar framework + BIST scoring engine). None of the comparable scanner projects include **news sentiment filtering** — they rely exclusively on price/volume/indicator signals. This is a gap because:

1. **The project already fetches qualitative context from Investing.com and Google Finance Beta** (per README), but this is manual AI-driven analysis, not an automated filter. The scoring engine has no way to downweight or flag stocks with recent negative news.
2. For BIST specifically, news sensitivity is higher than US markets: Turkish stocks often gap ±5–10% on macro announcements (central bank rates, currency interventions, geopolitical events). A stock that looks technically perfect can be ruined by a surprise rate hike.
3. The current system has no way to detect "news-driven" price moves vs. "organic technical" moves — both look the same in OHLCV data.

A simple news sentiment filter would add one more dimension: if recent headlines are net-negative for a stock, reduce its score by 5 points (configurable). If highly positive, boost by 3 points. This creates an automated "qualitative reinforcement layer" similar to what the AI agent does manually today.

## Acceptance Criteria
- [ ] New module `scripts/news_sentiment.py` that:
  - Queries a news source for recent articles about a given symbol (initially: Google News via RSS feed or Investing.com article list)
  - Applies a simple keyword-based sentiment score per headline using a curated Turkish + English keyword dictionary (positive: "growth", "profit", "upgrade"; negative: "loss", "downgrade", "debt")
  - Returns an aggregate sentiment score in range [-1, +1] for each symbol
- [ ] `scoring_engine.py` gains optional integration: if a sentiment score is provided via CLI flag `--sentiment <value>`, it adjusts the final score by `round(sentiment * 5)` (capped at ±10 points).
- [ ] `orchestrator.py` optionally calls news_sentiment for each scanned symbol when `config.yaml` has `news.enabled: true`. Results stored in pipeline output as `"sentiment_score"` per stock.
- [ ] Keyword dictionary is configurable via a YAML file (`data/sentiment_keywords.yaml`) so the user can add Turkish-specific terms (e.g., "rekor" = record/high, "düşüş" = decline).
- [ ] Graceful degradation: if news fetch fails, scoring continues normally with sentiment = 0 (neutral), logged as a warning.

## Constraints
- No external API keys required — uses free RSS feeds or web scraping. If both fail, falls back to neutral sentiment.
- Sentiment is **reinforcement only** (±10 max adjustment) — never flips a score from buy to sell territory on its own. Aligns with the project's philosophy that technicals drive decisions; sentiment reinforces them.
- Must not slow down the pipeline significantly: news fetch timeout of 5 seconds per symbol, parallelized via `concurrent.futures` (stdlib only).

## Notes
- Reference: The **Vibe-Trading** project connects "natural-language prompts to market-data loaders" — our approach is simpler but achieves a similar goal with less complexity.
- Future enhancement: swap keyword-based sentiment for a lightweight HuggingFace transformer model (`cardiffnlp/twitter-roberta-base-sentiment`) when GPU or higher CPU budget is available.
