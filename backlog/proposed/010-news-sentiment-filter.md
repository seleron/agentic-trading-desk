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

### Verified data-source findings (2026-08-27, EREGL — capability probe)

Empirically tested both libraries against EREGL; do not re-investigate from scratch:

- **yfinance `Ticker("EREGL.IS").news` returns `[]` — EMPTY.** Yahoo has no news feed for BIST tickers. Google News RSS is the only viable yfinance-side fallback for BIST.
- **borsapy `Ticker("EREGL").news` (a PROPERTY, not a method) returns a working DataFrame: ~20 latest KAP regulatory filings with columns `Date`, `Title`, `URL`.** Verified sample rows:
  - `20.08.2026 16:36:29` — "Borsada İşlem Gören Tipe Dönüşüm Duyurusu"
  - `14.08.2026 18:12:42` — "SPK İşlem Yasağı Nedeniyle Pay Duyurusu" (SPK trading ban — strongly negative)
  - `Date` is Turkish format `dd.mm.yyyy HH:MM:SS` — must be parsed with `dayfirst=True`.
- **KAP filings are regulatory announcements, not media headlines.** The filter should therefore **classify first, sentiment second**: known category → fixed polarity (e.g. "İşlem Yasağı" / trading restriction = strong negative; "Kazanç" (profit) = positive; "Zarar" (loss) = negative; "Temettü" (dividend) = mildly positive; "Pay Alım/Satım" (insider buy/sell) = polarity by direction). Free-text keyword scoring is only the fallback for unclassified titles.
- **borsapy `EVDS().search()` (KAP full-text search) returned EMPTY and requires an auth key — do NOT use it.** `Ticker.news` is the verified keyless path.
- **Repo tension:** borsapy was dropped from `requirements.txt` on 2026-08-11 (commit `593a7aa`) in favor of yfinance as the single data provider. This item RE-INTRODUCES borsapy — **strictly as an optional soft dependency** for the news path only: `try: import borsapy except ImportError: sentiment = 0 (neutral) + warning`. It must not touch the OHLCV data layer (stays yfinance `.IS`).

## Acceptance Criteria
- [ ] New module `scripts/news_sentiment.py` that:
  - **BIST primary source:** borsapy `Ticker(symbol).news` (KAP filings) via optional import; soft-degrades to neutral when borsapy is missing or the fetch fails.
  - **BIST fallback:** Google News RSS query by company name (e.g. "Ereğli Demir Çelik" / symbol) when borsapy is unavailable; stdlib `urllib` + XML parse only, 5s timeout.
  - **US source:** yfinance `Ticker(sym).news` (works for US tickers; still soft-degrade on empty list — treat empty as neutral, not as error).
  - **Classification layer (BIST):** category table mapping KAP title patterns → polarity weights (see verified samples above); unmatched titles fall through to keyword scoring.
  - **Keyword layer:** simple keyword-based sentiment score per headline using a curated Turkish + English keyword dictionary (positive: "growth", "profit", "upgrade", "kazanç", "rekor", "artış"; negative: "loss", "downgrade", "debt", "zarar", "düşüş", "yasağı", "ceza").
  - Returns an aggregate sentiment score in range [-1, +1] for each symbol.
- [ ] `scoring_engine.py` gains optional integration: if a sentiment score is provided via CLI flag `--sentiment <value>`, it adjusts the final score by `round(sentiment * 5)` (capped at ±10 points).
- [ ] `orchestrator.py` optionally calls news_sentiment for each scanned symbol when `config.yaml` has `news.enabled: true`. Results stored in pipeline output as `"sentiment_score"` per stock, plus `"sentiment_source"` (`kap` | `google_rss` | `yahoo` | `none`) so the user can see which path ran.
- [ ] Keyword + category tables live in a configurable YAML file (`data/sentiment_keywords.yaml`) so the user can add Turkish-specific terms without code changes.
- [ ] Graceful degradation: any news-fetch failure (import, network, parse, empty) → sentiment = 0 (neutral), logged as a warning, pipeline continues.
- [ ] Unit tests: KAP date parsing (`dd.mm.yyyy`), category classification on the two verified sample titles, keyword scoring, and the neutral-fallback path with borsapy import forced to fail.

## Constraints
- No external API keys required — borsapy KAP path is keyless (verified 2026-08-27); RSS is free. If all sources fail, fall back to neutral sentiment.
- borsapy stays an **optional** dependency (`requirements-optional.txt` or inline try/except); the CI gate must pass with borsapy NOT installed. Do NOT put borsapy back in `requirements.txt`.
- Sentiment is **reinforcement only** (±10 max adjustment) — never flips a score from buy to sell territory on its own. Aligns with the project's philosophy that technicals drive decisions; sentiment reinforces them.
- Must not slow down the pipeline significantly: news fetch timeout of 5 seconds per symbol, parallelized via `concurrent.futures` (stdlib only).
- Do NOT use borsapy `EVDS().search()` — verified empty/auth-required (2026-08-27 probe).

## Notes
- **Verification log (2026-08-27):** full borsapy-vs-yfinance capability probe against EREGL — raw results at `~` host `/tmp/bp-vs-yf-capability-20260827.json` (ephemeral; key findings are transcribed in "Verified data-source findings" above).
- Reference: The **Vibe-Trading** project connects "natural-language prompts to market-data loaders" — our approach is simpler and achieves a similar goal with less complexity.
- Future enhancement: swap keyword-based sentiment for a lightweight HuggingFace transformer model (`cardiffnlp/twitter-roberta-base-sentiment`) when GPU or higher CPU budget is available.
- Future: KAP filing *types* are enumerable per company — a `--kap-history` mode could detect "first trading ban in 6 months" style events rather than per-scan polarity.
