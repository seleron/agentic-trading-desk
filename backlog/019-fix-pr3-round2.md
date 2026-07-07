# Fix PR #3 round 2 — indentation, artifacts, pytest.ini
Area: review-fix
Rank: 0
PR: #3
Branch: autonomous/scaffolding

## Required fixes

### 1. Remove empty artifact files at repo root
- `ema20` and `ema50` are leftover from an earlier run (both 0 bytes)
- Delete them from the repo

### 2. Fix pytest.ini stale ignore path
```ini
[pytest]
testpaths = scripts
python_files = test_*.py
addopts = --ignore=agentic-trading-review-2   # <-- remove this line
```
The `agentic-trading-review-2` worktree was transient — baking it into committed config is unnecessary.

### 3. Fix orchestrator.py indentation regressions
Two locations (confirmed on current branch):

**Line ~179:** `# Step 3:` comment has only **3 spaces** instead of 4:
```python
   # Step 3: Multi-timeframe verification — weekly trend confirmation for daily signals
    print("[3/9] Running multi-timeframe analysis...")
```
Fix: align to 4-space indentation like the surrounding block.

**Line ~322:** `\"mtf_verification\":` dict key has **7 spaces** instead of 8:
```python
        \"notifications_count\": len(notifications),
       \"mtf_verification\": mtf_consensus,
        \"backtest_results\": backtest_results,
```
Fix: realign to 8-space indentation matching the rest of the dict.

### 4. Reconcile Step labels (minor)
Step 3 and Step 4 labels are present but inconsistent with other steps that use `# Step N:` prefix format. Keep consistent or drop — don't leave orphaned step comments mixed with numbered print statements like `[3/9]`.

## Acceptance
- `python3 -m unittest scripts.test_pipeline scripts.test_scoring_engine` passes (all existing tests)
- No regressions to pipeline output structure
- Clean git diff: only the 4 items above

## Constraints
- UPDATE `autonomous/scaffolding` branch
- Do not edit `test_data_quality.py`
- Push with descriptive commit messages matching fix keywords
