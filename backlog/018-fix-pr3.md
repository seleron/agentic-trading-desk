# Fix PR #3 review items — indentation, artifacts, pytest.ini
Area: review-fix
Rank: 0
PR: #3
Branch: autonomous/scaffolding

## Why
Claude Opus 4.8 requested changes on PR #3 (round 1). Commit `f2b7b1b` condensed the review feedback into this backlog item. Several items remain unfixed on the current branch.

## Required fixes

### 1. Remove accidental artifact files at repo root
- `ema20` — empty file (0 bytes)
- `ema50` — empty file (0 bytes)  
- `.hermes/pr2-body.md` — leftover PR body from earlier review cycle
- `agentic-trading-review-2/` — stray worktree directory (gitlink/submodule artifact)

### 2. Fix pytest.ini stale ignore path
Current:
```ini
[pytest]
testpaths = scripts
python_files = test_*.py
addopts = --ignore=agentic-trading-review-2   # ← remove this line
```
The `agentic-trading-review-2` worktree was transient — baking it into committed config is unnecessary noise.

### 3. Fix orchestrator.py indentation regressions (confirmed on disk)

**Line 179:** `# Step 3:` comment has **3 spaces** instead of 4:
```python
   # Step 3: Multi-timeframe verification — weekly trend confirmation for daily signals
    print("[3/9] Running multi-timeframe analysis...")
```
Fix: realign to 4-space indentation (same as surrounding block on line 180).

**Line 322:** `"mtf_verification":` dict key has **7 spaces** instead of 8:
```python
        "notifications_count": len(notifications),
       "mtf_verification": mtf_consensus,
        "backtest_results": backtest_results,
```
Fix: realign to 8-space indentation matching the rest of the dict literal.

## Acceptance
- `python3 -m unittest scripts.test_pipeline scripts.test_scoring_engine` passes (all existing tests)
- No regressions to pipeline output structure or EOD reporting
- Clean diff: only the 4 items above changed/removed

## Constraints
- UPDATE `autonomous/scaffolding` branch (do NOT open a new PR)
- Do not edit `test_data_quality.py` — restore from base if needed for gate
- Push commits with descriptive messages matching fix keywords (helps Claude fix-awareness)
