#!/usr/bin/env bash
#
# weekly-review.sh — Claude is the prioritization gate; emits weekly patch notes.
#
# Pipeline tail for the weekly routine:
#   1. Collect AI-drafted proposals (backlog/proposed/*), what shipped this week,
#      the project goal, and the EXISTING backlog (slugs + current ranks).
#   2. Ask Claude (headless `claude -p`, pure judgment, JSON out) to APPROVE/REJECT
#      each proposal AND produce ONE unified ranking over every open item
#      (existing-kept + newly-approved), plus human PATCH NOTES.
#   3. Promote approved proposals into backlog/NNN-<slug>.md, drop rejected, apply
#      Claude's unified ranks to ALL backlog items, push to the base branch, and
#      print the patch notes (the deliverable).
#
# Claude only judges (no repo writes); this script does the file moves. Safe.
# Mirrors Adverts-Project/scripts/hermes/weekly-review.sh (node → python3).

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"
source "$ROOT/scripts/hermes/lib-loop.sh"
LOOP_BASE_BRANCH="${LOOP_BASE_BRANCH:-autonomous/scaffolding}"

PROPOSED_DIR="backlog/proposed"
mapfile -t PROPOSALS < <(ls "$PROPOSED_DIR"/*.md 2>/dev/null | grep -v '/README\.md$' || true)

git fetch origin --quiet 2>/dev/null || true
SHIPPED="$(git log origin/main --since='7 days ago' --pretty='- %s (%h)' 2>/dev/null \
  || git log main --since='7 days ago' --pretty='- %s (%h)' 2>/dev/null || echo '(none)')"
GOAL="$(sed -n '1,12p' README.md 2>/dev/null)"

# Existing backlog with slug + current rank + title so Claude can rank them too.
EXISTING_BACKLOG="$(for f in backlog/[0-9]*.md; do
  [ -e "$f" ] || continue
  slug=$(basename "$f" .md | sed -E 's/^[0-9]+-//')
  rank=$(grep -m1 -iE '^rank:' "$f" | grep -oE '[0-9]+' | head -1)
  title=$(grep -m1 -iE '^title:' "$f" | sed -E 's/^[Tt]itle:[[:space:]]*//')
  [ -z "$title" ] && title=$(grep -m1 -E '^# ' "$f" | sed 's/^# //')
  echo "- slug=$slug | current_rank=${rank:-none} | $title"
done)"

PROPOSAL_BLOB=""
for f in "${PROPOSALS[@]}"; do
  [ -e "$f" ] || continue
  PROPOSAL_BLOB+=$'\n\n===== PROPOSAL FILE: '"$f"' =====\n'"$(cat "$f")"
done

PROMPT=$(cat <<PROMPT_EOF
You are Claude acting as the engineering-direction gate for an autonomous
improvement loop on the agentic-trading-desk repo (a Python deterministic
technical scanner/trade-planner). Base your decision ONLY on the information
below. Do NOT use any tools — reply with JSON only.

PROJECT GOAL:
$GOAL

WHAT SHIPPED TO main IN THE LAST 7 DAYS:
$SHIPPED

EXISTING OPEN BACKLOG (you may RE-RANK these; do not re-approve duplicates):
$EXISTING_BACKLOG

AI-DRAFTED PROPOSALS AWAITING YOUR DECISION:
${PROPOSAL_BLOB:-"(none this week)"}

TASK:
1. For each proposal, decide APPROVE or REJECT (approve only items that clearly
   serve the goal, aren't duplicates, are safe, are achievable with what the repo
   HAS — reject ideas resting on unverified premises like ccxt-BIST data or an
   empty learning DB — and are worth doing).
2. Produce a SINGLE UNIFIED RANKING over every OPEN item: each existing backlog
   item above that you are NOT rejecting, PLUS each proposal you approve. Give each
   a UNIQUE rank, 1 = highest priority, no ties and no gaps. Rank a strong new idea
   above existing items when warranted. (Rank 0 is reserved for review-fix items.)
3. Write concise PATCH NOTES for the user: what shipped this past week (from the
   git log) — what changed, any new behaviour — and what is newly queued (items
   you approved), with one-line whys.

Output ONLY this JSON object, no prose, no markdown fences:
{"approved":[{"slug":"<exact proposal filename slug, no dir/number/.md>","title":"<short>","reason":"<why>"}],
 "rejected":[{"slug":"<slug>","reason":"<why>"}],
 "ranking":[{"slug":"<slug of an open item: an existing one kept, or one you approved>","rank":<int>}],
 "patch_notes":"<markdown string for the user>"}
PROMPT_EOF
)

echo "Asking Claude to review ${#PROPOSALS[@]} proposal(s), re-rank backlog + draft notes..." >&2
RAW="$(claude -p "$PROMPT" 2>/dev/null)"

# Apply Claude's decision in python; capture patch notes (the deliverable) on stdout.
PATCH_NOTES="$(printf '%s' "$RAW" | python3 - <<'PY'
import json, os, re, sys, glob

raw = sys.stdin.read()
def parse(d):
    try:
        return json.loads(d)
    except Exception:
        a, b = d.find("{"), d.rfind("}")
        return json.loads(d[a:b+1])
try:
    j = parse(raw)
except Exception:
    sys.stderr.write("Could not parse Claude JSON:\n" + raw + "\n")
    sys.exit(1)

PDIR = "backlog/proposed"
def slug_of(fname):
    return re.sub(r"\.md$", "", re.sub(r"^\d+-", "", os.path.basename(fname)))

nums = [int(m.group(1)) for f in os.listdir("backlog")
        for m in [re.match(r"^(\d+)-", f)] if m]
nxt = (max(nums) + 1) if nums else 1

def proposed_files():
    if not os.path.isdir(PDIR):
        return []
    return [f for f in os.listdir(PDIR) if f.endswith(".md") and f != "README.md"]

def find_proposed(slug):
    fs = proposed_files()
    for f in fs:
        if slug_of(f) == slug:
            return f
    for f in fs:
        if slug in f:
            return f
    return None

# 1) promote approved proposals (rank applied in step 3)
for a in (j.get("approved") or []):
    src = find_proposed(a.get("slug", ""))
    if not src:
        sys.stderr.write("approved but no proposal file for slug: %s\n" % a.get("slug"))
        continue
    body = open(os.path.join(PDIR, src)).read().rstrip()
    dest = "backlog/%03d-%s.md" % (nxt, a["slug"]); nxt += 1
    open(dest, "w").write(body + "\n")
    os.remove(os.path.join(PDIR, src))
    sys.stderr.write("approved → %s\n" % dest)

# 2) drop rejected proposals
for r in (j.get("rejected") or []):
    src = find_proposed(r.get("slug", ""))
    if src:
        os.remove(os.path.join(PDIR, src))
        sys.stderr.write("rejected → removed %s\n" % src)

# 3) apply the unified ranking to ALL backlog items, by slug (rewrite `rank:` line)
rank_by = {x["slug"]: x["rank"] for x in (j.get("ranking") or []) if "slug" in x and "rank" in x}
for f in os.listdir("backlog"):
    if not re.match(r"^\d+-.*\.md$", f):
        continue
    slug = slug_of(f)
    if slug not in rank_by:
        continue
    p = os.path.join("backlog", f)
    body = open(p).read()
    if re.search(r"(?im)^rank:.*$", body):
        body = re.sub(r"(?im)^rank:.*$", "rank: %d" % rank_by[slug], body, count=1)
    else:
        # no rank line — inject just after the opening frontmatter fence, else at top
        if body.startswith("---"):
            body = re.sub(r"^---\n", "---\nrank: %d\n" % rank_by[slug], body, count=1)
        else:
            body = "rank: %d\n" % rank_by[slug] + body
    open(p, "w").write(body)
    sys.stderr.write("rank %d → %s\n" % (rank_by[slug], f))

sys.stdout.write((j.get("patch_notes") or "(no patch notes generated)") + "\n")
PY
)"

# Persist Claude-approved + re-ranked backlog to the loop base branch so the
# nightly job (which branches from it) sees them. Only when on that branch.
if [ -n "$(git status --porcelain backlog/ 2>/dev/null)" ]; then
  if [ "$(git rev-parse --abbrev-ref HEAD 2>/dev/null)" = "$LOOP_BASE_BRANCH" ]; then
    { flock 9
      git add backlog/ >/dev/null 2>&1
      git commit -q -m "Weekly review: promote + re-rank backlog (Claude-prioritized)" >/dev/null 2>&1 || true
      git push origin "HEAD:$LOOP_BASE_BRANCH" >/dev/null 2>&1 \
        && echo "  pushed backlog updates to $LOOP_BASE_BRANCH" >&2 \
        || echo "  ⚠️ push failed; backlog committed locally only" >&2
    } 9>"$LOOP_LOCK"
  else
    echo "  ⚠️ not on $LOOP_BASE_BRANCH (on $(git rev-parse --abbrev-ref HEAD)); leaving backlog changes uncommitted" >&2
  fi
fi

printf '%s\n' "$PATCH_NOTES"
