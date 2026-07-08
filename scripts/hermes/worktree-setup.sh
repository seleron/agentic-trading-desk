#!/usr/bin/env bash
#
# worktree-setup.sh — prepare a fresh loop worktree so the gate can run.
#
# This is a pure-Python repo whose only runtime deps (ccxt, pyyaml, yfinance)
# are installed system-wide, and the tests use the stdlib `unittest` — so unlike
# the Node adverts repo there is nothing to link. We just verify the deps import
# so a missing dependency surfaces here, not mid-gate. Kept for symmetry with
# the Adverts-Project worktree flow.
#
# Run once, from inside the new worktree, right after creating it.

set -uo pipefail

if python3 -c "import ccxt, yaml, yfinance" >/dev/null 2>&1; then
  echo "  deps importable (ccxt, pyyaml, yfinance)"
else
  echo "  ⚠️ one of ccxt/pyyaml/yfinance is not importable — run: pip install -r requirements.txt" >&2
fi
