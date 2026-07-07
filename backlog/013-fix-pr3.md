# Address Claude review on PR #3
Area: review-fix
Rank: 1
PR: #
%s
Branch: autonomous/scaffolding
Resolves-Backlog: 013-fix-pr3

## Why
Claude Opus 4.8 requested changes on PR #3 (round 1).

## Required fixes
["Fix the broken bt_run call in orchestrator.py: it now passes only bars= and capital= but run_backtest (unchanged in this PR) still requires pillar_weights, so the call raises TypeError and is swallowed by the except — either pass the pillar_weights you already compute above, or land the corresponding backtest.py default-mode change in the same PR so the signature actually supports the no-weights call the new test_run_backtest_default_score_mode asserts.","Split into one concern per PR as repeatedly requested: land pivot_risk scoring (scoring_engine.py + test_scoring_engine.py + test_data_quality.py pivot tests) alone; move MTF wiring, the orchestrator backtest step, the hermes pr-review.sh get()/python3 change, and pytest.ini into their own reviewed PRs.","Resolve the yfinance premise per owner guidance: the MTF and backtest orchestrator steps import yfinance, which is not in requirements.txt — either declare it or source weekly/history data from the existing ccxt ohlcv_data instead of a second undeclared provider; today those blocks silently degrade via except fallbacks.","Clean up the backlog/plan churn unrelated to the code change: the .hermes plan still lists MTF/backtest tasks as delivered, and 008-fix-pr2.md/pr2-cleanup-done.md duplicate each other — reconcile them with what this PR actually ships."]

## Acceptance
Unit tests pass; fixes addressed; re-review approves.
## Constraints
UPDATE the existing branch `autonomous/scaffolding` (do NOT open a new PR). Do not edit test_data_quality.py.
