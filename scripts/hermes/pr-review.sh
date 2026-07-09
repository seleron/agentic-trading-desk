#!/usr/bin/env bash
#
# pr-review.sh <pr-number> — Claude Opus 4.8 reviews an autonomous draft PR.
#
# Pipeline:
#   1. Independent gate: check out the PR branch in a throwaway worktree, RESTORE
#      the trusted scripts/ci.sh + metrics/baseline.json + scripts/test_*.py from
#      the base branch (so a tampered gate/weakened test can't fool us), run the
#      gate. Never trust the PR's own claim that tests pass.
#   2. Deterministic risk signals: did the diff touch the gate/tests? sensitive
#      files (config/scoring/indicators/weights)? how big is it?
#   3. Claude (claude -p) reviews the diff holistically vs the backlog item, with
#      the deterministic signals in hand.
#   4. Act (skipped when DRY_RUN=1):
#        REQUEST_CHANGES → comment on PR + file backlog/NNN-fix-pr<N>.md (rank 0,
#                          names the branch to UPDATE) + dispatch the implementer.
#        APPROVE + low-risk + gate-green + no-tamper → AUTO-MERGE (squash) → base.
#        APPROVE + higher-risk → comment + mark ready + notify a human to merge.
#        NEEDS_HUMAN → post questions, pause auto-fix for this PR.
#
# Auto-merge requires ALL of: Claude APPROVE, deterministic low-risk, trusted
# gate green, no gate/test tampering. Defense in depth. This is a Python CLI
# project (no web UI), so the "does it actually run" check lives inside ci.sh's
# functional smoke — there is no separate browser E2E phase.
#
# Mirrors Adverts-Project/scripts/hermes/pr-review.sh (E2E phase removed;
# all JSON parsing done with python3 to avoid the node-parse review bug).

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/hermes/lib-loop.sh"
PR="${1:?usage: pr-review.sh <pr-number>}"
BASE="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"
REPO="$(gh repo view --json nameWithOwner --jq .nameWithOwner 2>/dev/null || echo seleron/agentic-trading-desk)"
MAX_ROUNDS="${PR_REVIEW_MAX_ROUNDS:-8}"
REVIEW_HEADER="🤖 Claude Opus 4.8 review"   # keep in sync with pr-review-poll.sh grep
log(){ printf '%s\n' "$*" >&2; }

# jnorm: read possibly-messy stdin, print compact JSON (or empty if unparseable).
jnorm() {
  python3 -c "import json,sys
d=sys.stdin.read()
try:
    print(json.dumps(json.loads(d)))
except Exception:
    a=d.find('{'); b=d.rfind('}')
    try: print(json.dumps(json.loads(d[a:b+1])))
    except Exception: print('')"
}

# --- PR metadata -------------------------------------------------------------
meta="$(gh pr view "$PR" --json headRefName,baseRefName,isDraft,state,title,additions,deletions,files 2>/dev/null)"
[ -z "$meta" ] && { log "PR #$PR not found"; exit 1; }
HEAD_BRANCH="$(printf '%s' "$meta" | python3 -c 'import sys,json;print(json.load(sys.stdin)["headRefName"])')"
STATE="$(printf '%s' "$meta" | python3 -c 'import sys,json;print(json.load(sys.stdin)["state"])')"
[ "$STATE" != "OPEN" ] && { log "PR #$PR is $STATE — skipping"; exit 0; }
log "Reviewing PR #$PR (branch $HEAD_BRANCH → $BASE)"

git fetch origin "$HEAD_BRANCH" "$BASE" --quiet 2>/dev/null || true
DIFF="$(git diff "origin/$BASE...origin/$HEAD_BRANCH")"
FILES="$(git diff --name-only "origin/$BASE...origin/$HEAD_BRANCH")"
CHANGED_LINES="$(git diff --shortstat "origin/$BASE...origin/$HEAD_BRANCH" | grep -oE '[0-9]+ insertion|[0-9]+ deletion' | grep -oE '[0-9]+' | paste -sd+ | bc 2>/dev/null || echo 0)"

# Guard against an empty self-referential diff (e.g. head == base): nothing to review.
if [ -z "$FILES" ] || [ "${CHANGED_LINES:-0}" -eq 0 ]; then
  log "PR #$PR has no diff vs $BASE — skipping (empty/self-referential)."
  echo "ℹ️ PR #$PR has no changes vs $BASE — nothing to review."
  exit 0
fi

# Truncate very large diffs so Claude's context/JSON doesn't overflow.
MAX_DIFF_LINES=1500
if [ "${CHANGED_LINES:-0}" -gt "$MAX_DIFF_LINES" ]; then
  DIFF="… (diff truncated to last $MAX_DIFF_LINES lines — total ${CHANGED_LINES} changed across $(printf '%s\n' "$FILES" | wc -l) files; see full diff on the branch)"$'\n'"$(printf '%s\n' "$DIFF" | tail -n "$MAX_DIFF_LINES")"
fi

# Owner (human) PR comments — so a NEEDS_HUMAN decision can be answered in a PR
# comment and the next review run incorporates the answer. Exclude our own bot comments.
OWNER_COMMENTS="$(gh pr view "$PR" --json comments \
  --jq "[.comments[] | select((.body|test(\"$REVIEW_HEADER|Needs human|NEEDS HUMAN\"))|not) | .body] | .[-3:] | join(\"\n---\n\")" 2>/dev/null | head -c 4000 || true)"

# --- deterministic risk signals ---------------------------------------------
TAMPER="$(printf '%s\n' "$FILES" | grep -E '^(scripts/ci\.sh|metrics/baseline\.json|scripts/test_.*\.py)$' || true)"
SENSITIVE="$(printf '%s\n' "$FILES" | grep -iE 'config\.yaml|scoring_engine\.py|score\.py|indicators\.py|weight_optimizer\.py|macro_pillar\.py' || true)"
REQS="$(printf '%s\n' "$FILES" | grep -iE 'requirements\.txt|setup\.py|pyproject\.toml' || true)"
LOW_RISK=1
[ -n "$TAMPER" ] && LOW_RISK=0
[ -n "$SENSITIVE" ] && LOW_RISK=0
[ "${CHANGED_LINES:-0}" -gt 80 ] && LOW_RISK=0

# --- independent gate (trusted ci.sh + baseline + tests from base) -----------
WT="$(cd "$(dirname "$ROOT")" && pwd)/agentic-trading-review-$PR"
git worktree remove --force "$WT" >/dev/null 2>&1 || true; [ -d "$WT" ] && rm -rf "$WT"
git worktree add --detach "$WT" "origin/$HEAD_BRANCH" >/dev/null 2>&1
# Restore the TRUSTED gate + baselines + every test file from base so a PR cannot
# tamper the gate or weaken tests to pass.
git -C "$WT" checkout "origin/$BASE" -- scripts/ci.sh metrics/baseline.json >/dev/null 2>&1 || true
for tf in $(git -C "$WT" ls-tree --name-only "origin/$BASE" scripts/ | grep -E 'scripts/test_.*\.py$' || true); do
  git -C "$WT" checkout "origin/$BASE" -- "$tf" >/dev/null 2>&1 || true
done
log "Running trusted gate (may be slow)…"
GATE_LOG="$(cd "$WT" && timeout 420 bash scripts/ci.sh 2>&1)"; GATE_RC=$?
GATE_RESULT="FAIL"; printf '%s\n' "$GATE_LOG" | grep -q "GATE PASSED" && [ "$GATE_RC" -eq 0 ] && GATE_RESULT="PASS"
git worktree remove --force "$WT" >/dev/null 2>&1 || true; [ -d "$WT" ] && rm -rf "$WT"
log "Independent gate: $GATE_RESULT (rc=$GATE_RC); low_risk=$LOW_RISK; tamper='${TAMPER:-none}'; changed_lines=$CHANGED_LINES"

# --- Claude holistic review --------------------------------------------------
PROMPT=$(cat <<PROMPT_EOF
You are Claude Opus 4.8 reviewing an autonomous draft PR for the agentic-trading-desk
repo (a Python BIST/crypto technical-scoring tool — deterministic scoring, no web UI).
Judge holistically. Reply with JSON only — no tools, no prose.

PR #$PR — branch $HEAD_BRANCH → $BASE. Changed lines: $CHANGED_LINES.

DETERMINISTIC SIGNALS (computed, trustworthy):
- Independent gate (trusted ci.sh + tests restored from base): $GATE_RESULT
- Touches the gate/tests (ci.sh / baseline.json / test_*.py): ${TAMPER:-none}
- Touches sensitive files (config/scoring/indicators/weights): ${SENSITIVE:-none}
- Changes dependencies (requirements.txt etc.): ${REQS:-none}

CRITICAL RULES:
- If the gate FAILED, you must REQUEST_CHANGES.
- If the PR modified scripts/ci.sh, metrics/baseline.json, or a test file to make
  the gate pass (gate tampering / reward hacking), REQUEST_CHANGES and flag it as
  the top issue — never acceptable unless the backlog item explicitly demanded it.
- If it weakened/deleted existing tests to pass rather than fixing the code, REQUEST_CHANGES.
- NO HALF-ASSED SOLUTIONS. Do NOT APPROVE a feature that only *looks* done in the
  diff but does not actually deliver its value at runtime — e.g. imports that don't
  resolve, function signatures that don't match callers, config keys that don't
  exist, a feature gated-off-by-default or stubbed behind a flag. That is shipping
  something that only looks finished. REQUEST_CHANGES and say plainly why.
- VERIFY PREMISES. Many items assume data/an API/an access scope this repo may not
  have (e.g. ccxt has NO BIST support — BIST needs yfinance .IS; the learning module
  needs REAL trade history; a live broker/Robinhood MCP write path may not exist). If
  the change's value depends on a premise not established in this repo, treat it as
  unmet — do not pretend it's achievable.
- One concern per PR: scope creep is a REQUEST_CHANGES, not an APPROVE-with-caveat.
- TRACE NUMERIC SCALES / UNITS / RANGES. When the diff computes a value that is later
  compared to a threshold or combined with other values (scores, composites, ratios,
  normalized signals, prices vs pct), check that ALL such values share the SAME scale/
  range/unit. Work out the actual min/max a value can take and confirm every branch it
  feeds is REACHABLE. A comparison that can never be true (example: a composite normalized
  to the 0..1 range tested against a -0.5 exit threshold, so the exit never fires) is a
  logic bug even though it compiles and tests pass — REQUEST_CHANGES. Be especially
  suspicious when a PR changes how a value is normalized/scaled but does NOT touch the
  thresholds it feeds.
- Otherwise judge correctness, scope, and safety.

DECISION VALUES:
- APPROVE — works end-to-end and delivers its value; safe to merge (subject to gate).
- REQUEST_CHANGES — fixable in code by the autonomous loop; list concrete fixes.
- NEEDS_HUMAN — cannot be honestly completed by the loop because it rests on an unmet
  premise or needs a decision/input only the human owner can give (missing data/API/
  access, a cost or product tradeoff, ambiguous intent). Do NOT use this to dodge
  ordinary bugs. Put the specific blocking questions in "questions".

${OWNER_COMMENTS:+OWNER (HUMAN) PR COMMENTS — may answer a prior NEEDS_HUMAN question; factor these in:
$OWNER_COMMENTS
}
DIFF:
$DIFF

Output ONLY this JSON:
{"decision":"APPROVE|REQUEST_CHANGES|NEEDS_HUMAN","risk":"low|high",
 "summary":"<2-3 sentence holistic verdict>",
 "fixes":["<specific actionable fix>", "..."],   // empty unless REQUEST_CHANGES
 "questions":["<specific question the owner must answer>", "..."], // only for NEEDS_HUMAN
 "merge_safe":true|false}                          // true only if you'd merge as-is
PROMPT_EOF
)

log "Asking Claude Opus 4.8 to review…"
RAW="$(claude -p "$PROMPT" --model claude-opus-4-8 2>/dev/null)"
J="$(printf '%s' "$RAW" | jnorm)"
[ -z "$J" ] && { log "could not parse Claude review JSON:"; log "$RAW"; exit 1; }
get(){ printf '%s' "$J" | python3 -c "import json,sys
j=json.load(sys.stdin); v=j.get('$1')
print('\n'.join('- '+str(x) for x in v) if isinstance(v,list) else ('' if v is None else str(v)))"; }
DECISION="$(get decision)"; RISK="$(get risk)"; SUMMARY="$(get summary)"; FIXES="$(get fixes)"; MERGE_SAFE="$(get merge_safe)"; QUESTIONS="$(get questions)"

# Final auto-merge gate: defense in depth. (python json bool prints True/true.)
AUTO_MERGE=0
if [ "$DECISION" = "APPROVE" ] && { [ "$MERGE_SAFE" = "True" ] || [ "$MERGE_SAFE" = "true" ]; } \
   && [ "$GATE_RESULT" = "PASS" ] && [ "$LOW_RISK" = "1" ]; then AUTO_MERGE=1; fi

# Trailing section: questions for the owner (NEEDS_HUMAN) or required fixes.
if [ "$DECISION" = "NEEDS_HUMAN" ]; then
  TAIL_SECTION="$( [ -n "$QUESTIONS" ] && printf '### ❓ Questions for the owner (answer in a PR comment; the next loop run will pick it up)\n%s' "$QUESTIONS" )"
else
  TAIL_SECTION="$( [ -n "$FIXES" ] && printf '### Required fixes\n%s' "$FIXES" )"
fi

REVIEW_BODY="$(printf '## %s — %s (%s risk)\n\n%s\n\n**Independent gate:** %s · **changed lines:** %s · **gate/test edits:** %s · **sensitive files:** %s\n\n%s' \
  "$REVIEW_HEADER" "$DECISION" "$RISK" "$SUMMARY" "$GATE_RESULT" "$CHANGED_LINES" "${TAMPER:-none}" "${SENSITIVE:-none}" \
  "$TAIL_SECTION")"

echo "$J"   # stdout: the machine-readable verdict (for callers/telemetry)
log ""; log "=== DECISION: $DECISION (auto_merge=$AUTO_MERGE) ==="; log "$SUMMARY"

if [ "${DRY_RUN:-0}" = "1" ]; then log "(DRY_RUN — no PR comment / merge / backlog write)"; exit 0; fi

# --- act ---------------------------------------------------------------------
gh pr comment "$PR" --body "$REVIEW_BODY" >/dev/null 2>&1 || log "warn: could not comment"

if [ "$DECISION" = "APPROVE" ] && [ "$AUTO_MERGE" = "1" ]; then
  log "Auto-merging (low-risk, gate green, no tamper)…"
  gh pr ready "$PR" >/dev/null 2>&1 || true
  gh pr merge "$PR" --squash --delete-branch >/dev/null 2>&1 && log "merged #$PR" || log "merge failed"
  bash "$ROOT/scripts/hermes/backlog-reconcile.sh" "$PR" >&2 2>&1 || true
  echo "✅ PR #$PR auto-merged after Claude approval (low-risk); backlog reconciled."
elif [ "$DECISION" = "APPROVE" ]; then
  gh pr ready "$PR" >/dev/null 2>&1 || true
  echo "✅ PR #$PR APPROVED by Claude but higher-risk — marked ready; a human should merge."
elif [ "$DECISION" = "NEEDS_HUMAN" ]; then
  # The PR can't be honestly finished by the loop — it rests on an unmet premise or
  # needs an owner decision. Post questions (in REVIEW_BODY) and PAUSE: no fix item,
  # no implementer dispatch. The owner answers in a PR comment; the next review run
  # feeds OWNER_COMMENTS back into the prompt so the verdict can advance.
  gh pr comment "$PR" --body "🧑‍⚖️ **Needs human decision** — auto-fix is paused for this PR. Answer the questions above in a comment and the next loop run will pick it up." >/dev/null 2>&1 || true
  echo "🧑‍⚖️ PR #$PR needs a human decision — questions posted, auto-fix paused."
else
  # REQUEST_CHANGES → file a rank-0 fix item that UPDATES this branch.
  ROUND=$(( $(gh pr view "$PR" --json comments --jq "[.comments[]|select(.body|contains(\"$REVIEW_HEADER\"))]|length" 2>/dev/null || echo 0) ))
  if [ "$ROUND" -ge "$MAX_ROUNDS" ]; then
    gh pr comment "$PR" --body "⛔ **Needs human** — $MAX_ROUNDS Claude review rounds without resolution. Pausing the auto-fix loop for this PR." >/dev/null 2>&1 || true
    echo "⛔ PR #$PR hit $MAX_ROUNDS review rounds — escalated to a human (commented)."
  else
    # File/refresh a rank-0 fix item that UPDATES this PR's branch, inside a
    # throwaway DETACHED worktree on origin/$BASE (never the main checkout).
    BW="$(cd "$(dirname "$ROOT")" && pwd)/agentic-trading-fixfile-$PR"
    git worktree remove --force "$BW" >/dev/null 2>&1 || true; [ -d "$BW" ] && rm -rf "$BW"
    STATUS="⚠️ PR #$PR needs changes but could NOT file the fix item (worktree/push error) — auto-fix stalled, needs a human."
    FILED=0
    { flock 9
      git fetch origin "$BASE" -q 2>/dev/null || true
      if git worktree add --quiet --detach "$BW" "origin/$BASE" 2>/dev/null; then
        mkdir -p "$BW/backlog" 2>/dev/null
        slug="fix-pr${PR}"
        # Reuse the existing fix item for this PR if any (refresh it) — don't pile up
        # NNN-fix-prX on each round. Look in BASE's backlog.
        existing="$(cd "$BW" && grep -lE "^PR:[[:space:]]*#?$PR([^0-9]|\$)" backlog/[0-9]*.md 2>/dev/null | head -1)"
        if [ -n "$existing" ]; then
          f="$existing"
        else
          LAST_NUM="$(cd "$BW" && ls backlog/[0-9]*.md 2>/dev/null | sed -E 's#.*/([0-9]+)-.*#\1#' | sort -n | tail -1 | sed 's/^0*//')"
          f="backlog/$(printf '%03d' "$(( ${LAST_NUM:-0} + 1 ))")-$slug.md"
        fi
        # Accumulate the stems this PR resolves so the ORIGINAL feature item isn't
        # orphaned once this rank-0 fix becomes top and overwrites the PR body marker.
        fixstem="$(basename "$f" .md)"
        carried=""
        [ -n "$existing" ] && carried="$(grep -m1 -iE '^Resolves-Backlog:' "$BW/$existing" 2>/dev/null | sed -E 's/^[^:]*://' || true)"
        [ -z "$carried" ] && carried="$(gh pr view "$PR" --json body -q .body 2>/dev/null | grep -m1 -iE '^Resolves-Backlog:' | sed -E 's/^[^:]*://' || true)"
        allstems="$(printf '%s %s' "$carried" "$fixstem" | tr ', ' ' ' | tr -s ' ' '\n' | sed '/^$/d' | awk '!seen[$0]++' | paste -sd' ')"
        {
          echo "---"
          echo "rank: 0"
          echo "title: Address Claude review on PR #$PR"
          echo "area: review-fix"
          echo "---"
          echo "# Address Claude review on PR #$PR"
          echo "PR: #$PR"
          echo "Branch: $HEAD_BRANCH"
          echo "Resolves-Backlog: $allstems"
          echo
          echo "## Why"
          echo "Claude Opus 4.8 requested changes on PR #$PR (round $((ROUND+1)))."
          echo
          echo "## Required fixes"
          echo "$FIXES"
          echo
          echo "## Acceptance"
          echo "- Trusted gate passes: \`bash scripts/ci.sh\` prints GATE PASSED"
          echo "- Every fix above is addressed in the diff; no regressions"
          echo "- Re-review approves"
          echo
          echo "## Constraints"
          echo "- UPDATE the existing branch \`$HEAD_BRANCH\` (do NOT open a new PR)"
          echo "- Do NOT edit scripts/ci.sh, metrics/baseline.json, or test files to force a pass"
        } > "$BW/$f"
        if ( cd "$BW" && git add "$f" \
               && git commit -q -m "review: request changes on PR #$PR → $f" \
               && git push -q origin "HEAD:refs/heads/$BASE" ); then
          STATUS="🔧 PR #$PR needs changes — filed $f (rank 0)."
          FILED=1
        fi
      fi
    } 9>"$LOOP_LOCK"
    git worktree remove --force "$BW" >/dev/null 2>&1 || true; [ -d "$BW" ] && rm -rf "$BW"

    # Dispatch the implementer NOW rather than waiting for the 3am nightly: mark the
    # preconfigured nightly job to run on the gateway's next tick. Safe once per round.
    if [ "${FILED:-0}" = 1 ]; then
      if command -v hermes >/dev/null 2>&1; then HX=(hermes)
      else HX=("$HOME/.hermes/hermes-agent/venv/bin/python" -m hermes_cli.main); fi
      NID="$("${HX[@]}" cron list --all 2>/dev/null \
        | awk '/\[(active|paused)\]/{id=$1} /agentic-trading nightly improve/{print id; exit}')"
      if [ -n "$NID" ] && "${HX[@]}" cron run "$NID" >/dev/null 2>&1; then
        STATUS="🔧 PR #$PR needs changes — filed $f (rank 0) and dispatched the implementer now (job $NID); the PR branch will update shortly."
      else
        STATUS="🔧 PR #$PR needs changes — filed $f (rank 0); couldn't auto-dispatch the implementer — the nightly will pick it up."
      fi
    fi
    echo "$STATUS"
  fi
fi
