# Agentic Trading Desk — Operations Skill

## Quick Start

1. **Install dependencies:** `pip install ccxt pyyaml`
2. **Configure:** Edit `config.yaml` for pillar weights and thresholds
3. **Run analysis:** See script usage below

## Script Index

### Core (Original)
| Script | Purpose | Usage |
|--------|---------|-------|
| `scripts/indicators.py` | EMA/RSI/MACD/TRIX/Bollinger calculations | `python3 scripts/indicators.py input.json [--slope-lookback N]` |
| `scripts/macro_pillar.py` | Cross-asset macro sentiment (-2 to +2) | `python3 scripts/macro_pillar.py macro_input.json --json` |
| `scripts/score.py` | Three-pillar scoring + decision engine | `python3 scripts/score.py ticker_input.json [--json]` |

### New (Scaffolding Branch)
| Script | Purpose | Usage |
|--------|---------|-------|
| `scripts/data_fetcher.py` | Multi-exchange data via ccxt (replaces Robinhood) | `python3 scripts/data_fetcher.py BINANCE BTC/USDT 1d --json` |
| `scripts/multi_timeframe.py` | Multi-timeframe confirmation analysis | `cat mtf.json \| python3 scripts/multi_timeframe.py --stdin` |
| `scripts/trade_plan.py` | Structured trade plan generation (entry/stop/targets) | `python3 scripts/trade_plan.py --score scorecard.json [--capital N]` |
| `scripts/weight_optimizer.py` | Hyperopt-style weight optimization (grid/random search) | `python3 scripts/weight_optimizer.py --mode grid --input history.json` |
| `scripts/backtest.py` | Walk-forward backtesting with slippage/commission | `python3 scripts/backtest.py --input bars.json --weights trend=0.4 momentum=0.35 macro_sentiment=0.25` |

## Autonomous Workflow (Recommended)

```
1. Fetch data:    python3 scripts/data_fetcher.py BINANCE BTC/USDT 1d
2. Macro scan:   python3 scripts/macro_pillar.py macro_input.json --json
3. Score tickers: python3 scripts/score.py ticker_input.json --json
4. MTF confirm:  cat mtf_input.json | python3 scripts/multi_timeframe.py --stdin
5. Generate plan:python3 scripts/trade_plan.py --score scorecard.json --capital 10000
6. Optimize:     python3 scripts/weight_optimizer.py --mode optimize --input history.json --iterations 1000
7. Backtest:     python3 scripts/backtest.py --input bars.json --output results.json
```

## Configuration (config.yaml)

All pillar weights and scoring thresholds are in `config.yaml`. Key sections:
- **pillar_weights**: Relative weight of Trend vs Momentum vs Macro-Sentiment
- **trend_scoring**: EMA periods, slope lookback
- **momentum_scoring**: RSI/MACD/TRIX parameters
- **macro_scoring**: Cross-asset component weights
- **data_fetcher**: Default exchange and timeframe

## Guardrails (Same as original)

1. Protected tickers never evaluated for selling
2. Account segregation: Agentic (cash) vs Individual (margin)
3. T+1 liquidity check before buy orders
4. Mandatory user confirmation before any order execution
5. Adverse macro caps pillar at -1 even if composite is higher

## BIST Support

For Borsa Istanbul stocks, use `fetch_bist_data()` in data_fetcher.py:
```python
from scripts.data_fetcher import fetch_bist_data
data = fetch_bist_data("THYAO", timeframe="1d", limit=300)
# Returns OHLCV compatible with indicators.py
```

## Dependencies

- **Required**: Python 3.9+, ccxt, pyyaml
- **Optional**: scipy (for advanced optimization)
