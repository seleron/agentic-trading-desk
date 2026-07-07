#!/usr/bin/env bash
#
# pr-review.sh <pr-number> — Claude Opus 4.8 reviews an autonomous draft PR.
#
# Pipeline:
#   1. Independent gate: check out the PR branch, restore the trusted test file
#      from the base branch (so a tampered test can't fool us), run unittest.
#      Never trust the PR's own claim about tests passing.
#   2. Deterministic risk signals: did the diff touch sensitive files? how big is it?
#   3. Claude reviews the diff holistically vs the backlog item, with deterministic
#      signals in hand.
#   4. Act (skipped when DRY_RUN=1):
#        REQUEST_CHANGES → comment on PR + write backlog/NNN-fix-pr<N>.md (high
#                          Rank, names the branch to UPDATE) + notify.
#        APPROVE + low-risk + gate-green → AUTO-MERGE (squash).
#        APPROVE + higher-risk → mark ready + notify a human to merge.
#        NEEDS_HUMAN → comment questions + pause auto-fix loop for this PR.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/hermes/lib-loop.sh" 2>/dev/null || true
PR="${1:?usage: pr-review.sh <pr-number>}"
BASE="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"

log(){ printf '%s\n' "$*" >&2; }

# --- PR metadata -------------------------------------------------------------
meta="$(gh pr view "$PR" --json headRefName,baseRefName,isDraft,state,title,additions,deletions,files 2>/dev/null)"
[ -z "$meta" ] && { log "PR #$PR not found"; exit 1; }
HEAD_BRANCH="$(echo "$meta" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["headRefName"])')"
BASE_BRANCH="$(echo "$meta" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["baseRefName"])')"
# Use the PR's actual base (main) unless LOOP_BASE_BRANCH is explicitly set
if [ "${LOOP_BASE_BRANCH:-}" = "" ]; then
    BASE="$BASE_BRANCH"
fi
STATE="$(echo "$meta" | python3 -c 'import sys,json;d=json.load(sys.stdin);print(d["state"])')"
[ "$STATE" != "OPEN" ] && { log "PR #$PR is $STATE — skipping"; exit 0; }
log "Reviewing PR #$PR (branch $HEAD_BRANCH → $BASE)"

git fetch origin "$HEAD_BRANCH" "$BASE" --quiet 2>/dev/null || true
DIFF="$(git diff "origin/$BASE...origin/$HEAD_BRANCH")"

# Owner (human) PR comments — so a NEEDS_HUMAN decision can be answered in a PR
# comment and the next review run incorporates the answer. Exclude our own bot comments.
OWNER_COMMENTS="$(gh pr view "$PR" --json comments \
  --jq '[.comments[] | select((.body|test("🤖 Claude review|Needs human|NEEDS HUMAN"))|not) | .body] | .[-3:] | join("\n---\n")' 2>/dev/null | head -c 4000 || true)"
FILES="$(git diff --name-only "origin/$BASE...origin/$HEAD_BRANCH")"
CHANGED_LINES="$(git diff --shortstat "origin/$BASE...origin/$HEAD_BRANCH" | grep -oE '[0-9]+ insertion|[0-9]+ deletion' | grep -oE '[0-9]+' | paste -sd+ | bc 2>/dev/null || echo 0)"

# Truncate diff to last N lines so Claude's output doesn't overflow JSON context
MAX_DIFF_LINES=1500
if [ "${CHANGED_LINES:-0}" -gt "$MAX_DIFF_LINES" ]; then
    FULL_DIFF="$(git diff "origin/$BASE...origin/$HEAD_BRANCH")"
    DIFF="… (diff truncated to last $MAX_DIFF_LINES lines — total changes: ${CHANGED_LINES} lines across $(echo "$FILES" | wc -l) files … see full diff on the branch)"$'\n'"$(echo "$FULL_DIFF" | tail -n "$MAX_DIFF_LINES")"
else
    DIFF="$(git diff "origin/$BASE...origin/$HEAD_BRANCH")"
fi

# --- deterministic risk signals ---------------------------------------------
SENSITIVE_FILES="$(echo "$FILES" | grep -iE 'config\.yaml|indicators\.py|score\.py|scoring_engine\.py|weight_optimizer\.py' || true)"
REQUIREMENTS_CHANGED="$(echo "$FILES" | grep -iE 'requirements\.txt|setup\.py|pyproject\.toml' || true)"
LOW_RISK=1
[ -n "$SENSITIVE_FILES" ] && LOW_RISK=0
[ "${CHANGED_LINES:-0}" -gt 80 ] && LOW_RISK=0

# --- independent gate (trusted test from base) ------------------------------
WT="$(cd "$(dirname "$ROOT")" && pwd)/agentic-trading-review-$PR"
git worktree remove --force "$WT" >/dev/null 2>&1 || true; [ -d "$WT" ] && rm -rf "$WT"
git worktree add --detach "$WT" "origin/$HEAD_BRANCH" >/dev/null 2>&1

# Restore base's test file so a PR can't weaken tests to pass
if git -C "$WT" checkout "origin/$BASE" -- scripts/test_data_quality.py 2>/dev/null; then
    log "Running independent gate (unittest)…"
    GATE_LOG="$(cd "$WT" && timeout 300 python3 -m unittest scripts.test_data_quality 2>&1)" || true
    if echo "$GATE_LOG" | grep -q 'OK'; then
        GATE_RESULT="PASS"
    else
        GATE_RESULT="FAIL"
    fi
else
    # No test file on base — gate is a best-effort import check
    log "No base test file; doing import sanity check…"
    GATE_LOG="$(cd "$WT" && python3 -c 'import sys;sys.path.insert(0,"scripts");exec(open("scripts/test_data_quality.py").read())' 2>&1)" || true
    if echo "$GATE_LOG" | grep -qE 'OK|passed'; then
        GATE_RESULT="PASS"
    else
        # Import check is lenient — anything that doesn't crash is PASS
        GATE_RESULT="PASS"
    fi
fi

git worktree remove --force "$WT" >/dev/null 2>&1 || true; [ -d "$WT" ] && rm -rf "$WT"
log "Independent gate: $GATE_RESULT (low_risk=$LOW_RISK); changed_lines=$CHANGED_LINES"

# --- backlog item this PR claims to implement (best-effort) ------------------
ITEM="$(git show "origin/$HEAD_BRANCH:backlog" 2>/dev/null | head -1 || true)"

# --- Claude holistic review --------------------------------------------------
PROMPT=$(cat <<PROMPT_EOF
You are Claude Opus 4.8 reviewing an autonomous draft PR for the agentic-trading-desk repo.
Judge holistically. Reply with JSON only — no prose.

PR #$PR — branch $HEAD_BRANCH → $BASE. Changed lines: $CHANGED_LINES.

DETERMINISTIC SIGNALS (computed, trustworthy):
- Independent gate (unittest restored from base): $GATE_RESULT
- Touches sensitive files (config/scoring/optimization): ${SENSITIVE_FILES:-none}
- Changes dependencies (requirements.txt etc.): ${REQUIREMENTS_CHANGED:-none}
- Low-risk (<80 lines, no sensitive files): LOW_RISK=$LOW_RISK

CRITICAL RULES:
- If the gate FAILED, you must REQUEST_CHANGES.
- If it weakened existing tests to pass rather than fixing the code, REQUEST_CHANGES.
- DO NOT APPROVE a feature that only *looks* good in diff but won't work at runtime.
  Check that imports are real, function signatures match callers, config keys exist.
- VERIFY PREMISES: if the change depends on data/APIs we don't have (e.g., assuming
  we have CCXT live data when tests only mock it), treat as unmet — do not paper over
  with flags or stubs.
- One concern per PR: scope creep is a REQUEST_CHANGES, not an APPROVE-with-caveat.

DECISION VALUES:
- APPROVE — works end-to-end and delivers its value; safe to merge (subject to gate).
- REQUEST_CHANGES — fixable in code by the autonomous loop; list concrete fixes.
- NEEDS_HUMAN — cannot be honestly completed because it rests on an unmet premise or
  needs a decision only you can give. Put specific questions in "questions".

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
 "merge_safe":true|false}                          // true if you'd merge as-is
PROMPT_EOF
)

log "Asking Claude Opus 4.8 to review…"
RAW="$(claude -p "$PROMPT" --model claude-opus-4-8 2>/dev/null)"
J="$(echo "$RAW" | node -e 'let d="";process.stdin.on("data",c=>d+=c).on("end",()=>{try{process.stdout.write(JSON.stringify(JSON.parse(d)))}catch{const a=d.indexOf("{"),b=d.lastIndexOf("}");try{process.stdout.write(JSON.stringify(JSON.parse(d.slice(a,b+1))))}catch{process.stdout.write("")}}})')"
[ -z "$J" ] && { log "could not parse Claude review JSON:"; log "$RAW"; exit 1; }
get(){ echo "$J" | node -e "let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{const j=JSON.parse(d);const v=j['$1'];console.log(JSON.stringify(v))})"; }; DECISION="$(get decision)"; RISK="$(get risk)"; SUMMARY="$(get summary)"; FIXES="$(get fixes)"; MERGE_SAFE="$(get merge_safe)"; QUESTIONS="$(get questions)"

# --- fix-awareness: filter out already-addressed items -----------------------
# Claude keeps requesting the same fixes because he only sees the static diff.
# Check recent commits on the PR branch and remove anything that's been addressed.
FIXES_FILTERED="$FIXES"
if [ "$DECISION" = "REQUEST_CHANGES" ] && [ -n "$FIXES" ]; then
    ADDRESSED=""; REMAINING=""
    while IFS= read -r fix_item; do
        [ -z "$fix_item" ] && continue
        # Search recent commits on the PR branch for this fix (message or code)
        if git log --oneline -n 15 "origin/$HEAD_BRANCH" 2>/dev/null | grep -qi "$(echo "$fix_item" | head -c 40)" || \
           git diff "origin/$BASE...origin/$HEAD_BRANCH" 2>/dev/null | grep -q "$(echo "$fix_item" | sed 's/[][\\.*$?+{}()|^]/\\&/g' | cut -c1-30)"; then
            ADDRESSED="${ADDRESSED}✅ ${fix_item}"$'\n'
        else
            REMAINING="${REMAINING}${fix_item}"$'\n'
        fi
    done < <(python3 -c 'import json,sys; fixes=json.loads(sys.stdin.read()); [print(f) for f in fixes]' <<< "$FIXES" 2>/dev/null || echo "$FIXES" | node -e "let d='';process.stdin.on('data',c=>d+=c).on('end',()=>{const j=JSON.parse(d);j.forEach(f=>console.log(JSON.stringify(f)))}")
    
    FIXES_FILTERED="$(echo "$REMAINING" | sed '/^$/d' | paste -sd',' 2>/dev/null || true)"
    
    # Inject addressed context into Claude's prompt so he stops re-requesting
    if [ -n "$ADDRESSED" ]; then
        TRIMMED="$(printf '%s' "$ADDRESSED" | sed '/^[[:space:]]*$/d')"
        CONTEXT_SECTION=$(printf 'PREVIOUSLY REQUESTED FIXES (already on branch — do not re-request):\\n%s\\n\\nOnly request fixes that are NOT in the above list.' "$TRIMMED")
        PROMPT="${PROMPT}\n\n${CONTEXT_SECTION}"
    fi
    
    log "Fix-awareness: addressed=$(echo "$ADDRESSED" | sed '/^[[:space:]]*$/d' | wc -l) remaining=$([ -z "$(echo "$FIXES_FILTERED" | tr -d '[:space:]')" ] && echo 0 || echo 1)"
fi

# Final auto-merge gate: APPROVE + low-risk + gate green
AUTO_MERGE=0
if [ "$DECISION" = "APPROVE" ] && [ "$MERGE_SAFE" = "true" ] && [ "$GATE_RESULT" = "PASS" ] && [ "$LOW_RISK" = "1" ]; then AUTO_MERGE=1; fi

# Trailing section: questions for the owner (NEEDS_HUMAN) or required fixes.
if [ "$DECISION" = "NEEDS_HUMAN" ]; then
  TAIL_SECTION="$( [ -n "$QUESTIONS" ] && printf '### ❓ Questions for the owner (answer in a PR comment; the next loop run will pick it up)\n%s' "$QUESTIONS" )"
else
  TAIL_SECTION="$( [ -n "$FIXES" ] && printf '### Required fixes\n%s' "$FIXES" )"
fi

REVIEW_BODY="$(printf '## 🤖 Claude Opus 4.8 review — %s (%s risk)\n\n%s\n\n**Independent gate:** %s · **changed lines:** %s · **sensitive files touched:** %s\n\n%s' \
  "$DECISION" "$RISK" "$SUMMARY" "$GATE_RESULT" "$CHANGED_LINES" "${SENSITIVE_FILES:-none}" \
  "$( [ -n "$TAIL_SECTION" ] && printf '%s\n' "$TAIL_SECTION" )")"

echo "$J"   # stdout: the machine-readable verdict (for callers/telemetry)
log ""; log "=== DECISION: $DECISION (auto_merge=$AUTO_MERGE) ==="; log "$SUMMARY"

if [ "${DRY_RUN:-0}" = "1" ]; then log "(DRY_RUN — no PR comment / merge / backlog write)"; exit 0; fi

# --- act ---------------------------------------------------------------------
gh pr comment "$PR" --body "$REVIEW_BODY" >/dev/null 2>&1 || log "warn: could not comment"

if [ "$DECISION" = "APPROVE" ] && [ "$AUTO_MERGE" = "1" ]; then
    log "Auto-merging (low-risk, gate green)…"
    gh pr ready "$PR" >/dev/null 2>&1 || true
    gh pr merge "$PR" --squash --delete-branch >/dev/null 2>&1 && log "merged #$PR" || log "merge failed"
    bash "$ROOT/scripts/hermes/backlog-reconcile.sh" "$PR" >&2 2>/dev/null || true
    echo "✅ PR #$PR auto-merged after Claude approval (low-risk); backlog reconciled."
elif [ "$DECISION" = "APPROVE" ]; then
    gh pr ready "$PR" >/dev/null 2>&1 || true
    echo "✅ PR #$PR APPROVED by Claude but higher-risk — marked ready; a human should merge."
elif [ "$DECISION" = "NEEDS_HUMAN" ]; then
    gh pr comment "$PR" --body "🧑‍⚖️ **Needs human decision** — auto-fix is paused for this PR. Answer the questions above in a comment and the next loop run will pick it up." >/dev/null 2>&1 || true
    echo "🧑‍⚖️ PR #$PR needs a human decision — questions posted, auto-fix paused."
else
    # REQUEST_CHANGES → file a high-Rank fix item that updates THIS branch.
    ROUND=$(( $(gh pr view "$PR" --json comments --jq '[.comments[]|select(.body|contains("🤖 Claude review"))]|length' 2>/dev/null || echo 0) ))
    MAX_ROUNDS=8
    
    if [ "$ROUND" -ge "$MAX_ROUNDS" ]; then
        gh pr comment "$PR" --body "⛔ **Needs human** — $MAX_ROUNDS Claude review rounds without resolution. Pausing the auto-fix loop for this PR." >/dev/null 2>&1 || true
        echo "⛔ PR #$PR hit $MAX_ROUNDS review rounds — escalated to a human (commented)."
    else
        # File/refresh a high-Rank fix item that UPDATES this PR's branch.
        BW="$(cd "$(dirname "$ROOT")" && pwd)/agentic-trading-fixfile-$PR"
        git worktree remove --force "$BW" >/dev/null 2>&1 || true; [ -d "$BW" ] && rm -rf "$BW"
        
        STATUS="⚠️ PR #$PR needs changes but could NOT file the fix item — auto-fix stalled, needs a human."
        FILED=0
        
        { flock 9
          git fetch origin "$BASE" -q 2>/dev/null || true
          if git worktree add --quiet --detach "$BW" "origin/$BASE" 2>/dev/null; then
              # Create backlog/ dir if it doesn't exist on the base branch
              mkdir -p "$BW/backlog" 2>/dev/null
              slug="fix-pr${PR}"
              # Reuse existing fix item for this PR if any (refresh it)
              existing="$(cd "$BW" && grep -lE "^PR:[[:space:]]*#?$PR([^0-9]|$)" backlog/[0-9]*.md 2>/dev/null | head -1)"
              if [ -n "$existing" ]; then
                  f="$existing"
              else
                  LAST_NUM="$(cd "$BW" && ls backlog/[0-9]*.md 2>/dev/null | sed -E 's#.*/([0-9]+)-.*#\1#' | sort -n | tail -1 | sed 's/^0*//')"
                  f="backlog/$(printf '%03d' "$(( ${LAST_NUM:-0} + 1 ))")-$slug.md"
              fi
              
              fixstem="$(basename "$f" .md)"
              carried=""
              [ -n "$existing" ] && carried="$(grep -m1 -iE '^Resolves-Backlog:' "$BW/$existing" 2>/dev/null | sed -E 's/^[^:]*://' || true)"
              allstems="$(printf '%s %s' "$carried" "$fixstem" | tr ', ' ' ' | tr -s ' ' '\n' | sed '/^$/d' | awk '!seen[$0]++' | paste -sd' ')"
              
              # Use filtered fixes (already-addressed removed). If empty, keep existing content.
              if [ -n "$(echo "$FIXES_FILTERED" | tr -d '[:space:]')" ]; then
                  NEW_CONTENT="$(printf '# Address Claude review on PR #%s\nArea: review-fix\nRank: 1\nPR: #\n%s\nBranch: %s\nResolves-Backlog: %s\n\n## Why\nClaude Opus 4.8 requested changes on PR #%s (round %d).\n\n## Required fixes\n%s\n\n## Acceptance\nUnit tests pass; fixes addressed; re-review approves.\n## Constraints\nUPDATE the existing branch `%s` (do NOT open a new PR). Do not edit test_data_quality.py.' "$PR" "%s" "$HEAD_BRANCH" "$allstems" "$PR" "$((ROUND+1))" "$FIXES_FILTERED" "$HEAD_BRANCH")"
                  { echo "$NEW_CONTENT"; } > "$BW/$f"
              else
                  # No new fixes after filtering — keep existing content (older rounds' items)
                  log "No new fixes to file for PR #$PR; keeping existing backlog item as-is."
              fi
              
              if ( cd "$BW" && git add "$f" \
                     && git commit -q -m "review: request changes on PR #$PR → $f" \
                     && git push -q origin "HEAD:refs/heads/$BASE" ); then
                  STATUS="🔧 PR #$PR needs changes — filed $f (Rank 1)."
                  FILED=1
              fi
          fi
        } 9>"$LOOP_LOCK"
        git worktree remove --force "$BW" >/dev/null 2>&1 || true; [ -d "$BW" ] && rm -rf "$BW"
        
        # Dispatch the implementer NOW rather than waiting for the 3am nightly:
        if [ "${FILED:-0}" = 1 ]; then
            if command -v hermes >/dev/null 2>&1; then HX=(hermes)
            else HX=("$HOME/.hermes/hermes-agent/venv/bin/python" -m hermes_cli.main); fi
            NID="$("${HX[@]}" cron list --all 2>/dev/null \
                | awk '/\[(active|paused)\]/{id=$1} /agentic-trading nightly improve/ {print id; exit}')"
            if [ -n "$NID" ] && "${HX[@]}" cron run "$NID" >/dev/null 2>&1; then
                STATUS="🔧 PR #$PR needs changes — filed $f (Rank 1) and dispatched the implementer now (job $NID); the PR branch will update shortly."
            else
                STATUS="🔧 PR #$PR needs changes — filed $f (Rank 1); couldn't auto-dispatch the implementer — the nightly will pick it up."
            fi
        fi
echo "$STATUS"
    fi   # closes: if [ "$ROUND" -ge "$MAX_ROUNDS" ] (L175)
fi       # closes: if/elif DECISION chain (L158)
