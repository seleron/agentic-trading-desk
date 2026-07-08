#!/usr/bin/env bash
#
# ci.sh — the deterministic quality gate for the autonomous improvement loop.
#
# NO LLM runs here. This is the gatekeeper: it must give the same pass/fail for
# the same code every time, so the loop (and humans) can trust it. See
# docs/AUTONOMOUS-LOOP.md.
#
# Layers (all host-safe — pure Python stdlib + the repo's deps, no Docker):
#   1. Syntax        — every module under scripts/ byte-compiles (absolute).
#   2. Unit tests    — python3 -m unittest discover (absolute; must end "OK").
#   3. Test ratchet  — test count must be >= metrics/baseline.json:minTests
#                      (anti-drift: you cannot delete/weaken tests to pass).
#   4. Functional smoke — score a synthetic bullish quote end-to-end and assert
#                      the score is a number in [0,100] (offline; proves the
#                      pipeline actually RUNS, not just compiles).
#
# Exit 0 + "GATE PASSED" = gate passed. Non-zero = blocked (do not merge).

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
BASELINE="$ROOT/metrics/baseline.json"
FAILED=0

step()  { printf '\n\033[1m=== %s ===\033[0m\n' "$1"; }
pass()  { printf '\033[32m✓ %s\033[0m\n' "$1"; }
fail()  { printf '\033[31m✗ %s\033[0m\n' "$1"; FAILED=1; }
warn()  { printf '\033[33m⚠ %s\033[0m\n' "$1"; }

# Read a numeric field from baseline.json (stdlib only; prints "null" if absent).
baseline_num() {
  python3 -c "import json,sys
try:
    b=json.load(open('$BASELINE'))
    v=b.get('$1')
    print('null' if v is None else v)
except Exception:
    print('null')"
}

# --- 1/4 Syntax (absolute) ---------------------------------------------------
step "1/4 Syntax — byte-compile scripts/ (absolute)"
if python3 -m compileall -q scripts >/tmp/ci-compile.log 2>&1; then
  pass "all modules compile"
else
  fail "syntax error(s) — see below"
  cat /tmp/ci-compile.log
fi

# --- 2/4 Unit tests (absolute) ----------------------------------------------
step "2/4 Unit tests — unittest discover (absolute)"
TEST_LOG="$(python3 -m unittest discover -s scripts -p 'test_*.py' 2>&1)"; TEST_RC=$?
# unittest prints its summary ("Ran N tests", "OK"/"FAILED") to stderr, captured above.
RAN_TESTS="$(printf '%s\n' "$TEST_LOG" | grep -oE '^Ran [0-9]+ test' | grep -oE '[0-9]+' | head -1)"
if [ "$TEST_RC" -eq 0 ] && printf '%s\n' "$TEST_LOG" | grep -qE '^OK'; then
  pass "unit tests green (ran ${RAN_TESTS:-?})"
else
  fail "unit tests failing"
  printf '%s\n' "$TEST_LOG" | tail -30
fi

# --- 3/4 Test-count ratchet (anti-drift) ------------------------------------
step "3/4 Test-count ratchet (vs baseline)"
MIN_TESTS="$(baseline_num minTests)"
if [ "$MIN_TESTS" = "null" ] || [ -z "$MIN_TESTS" ]; then
  warn "no minTests in baseline.json — ratchet skipped (add \"minTests\" to enforce)"
elif [ -z "${RAN_TESTS:-}" ]; then
  fail "could not count tests — cannot verify ratchet"
elif [ "$RAN_TESTS" -lt "$MIN_TESTS" ]; then
  fail "test count dropped: $RAN_TESTS < baseline minTests $MIN_TESTS (ratchet violated — did you delete/weaken tests?)"
elif [ "$RAN_TESTS" -gt "$MIN_TESTS" ]; then
  pass "test count UP: $RAN_TESTS > baseline $MIN_TESTS — bump minTests in metrics/baseline.json"
else
  pass "test count steady at baseline ($MIN_TESTS)"
fi

# --- 4/4 Functional smoke (offline) -----------------------------------------
step "4/4 Functional smoke — score a synthetic quote end-to-end (offline)"
SMOKE="$(python3 -c "
import sys
sys.path.insert(0, 'scripts')
from test_pipeline import _bullish_quote
from scoring_engine import score_quote
s = score_quote(_bullish_quote())['score']
assert isinstance(s, (int, float)), 'score is not numeric: %r' % (s,)
assert 0 <= s <= 100, 'score out of range: %r' % (s,)
print('smoke score = %s' % s)
" 2>&1)"; SMOKE_RC=$?
if [ "$SMOKE_RC" -eq 0 ]; then
  pass "pipeline runs — $SMOKE"
else
  fail "functional smoke crashed"
  printf '%s\n' "$SMOKE" | tail -15
fi

# --- verdict -----------------------------------------------------------------
echo
if [ "$FAILED" -eq 0 ]; then
  printf '\033[1;32mGATE PASSED\033[0m\n'
  exit 0
else
  printf '\033[1;31mGATE FAILED\033[0m\n'
  exit 1
fi
