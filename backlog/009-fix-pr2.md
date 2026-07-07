# Address Claude review on PR #2 (rounds 1–5)

## Required fixes:
- 'Fix the failing independent unittest gate — restore/repair the broken test (do not weaken it) and confirm the full suite passes green before re-review.'
- Split into one concern per PR: land pivot_risk scoring (scoring_engine.py + tests + orchestrator r2/s2 population) alone; move the MTF orchestrator wiring and the backtest.py full-engine integration into their own separate PRs.
- Guard the backtest step's runtime `import yfinance` so the orchestrator degrades safely when yfinance is absent (the MTF block falls back to daily, but the backtest import is unguarded and will raise).
- Fix the stray under-indented lines in orchestrator.py: the `# Step 3:` comment at 3 spaces and the `"mtf_verification"` dict key at 7 spaces.
