#!/usr/bin/env bash
#
# research-context.sh — preprocessor for the weekly research+propose routine.
# Stdout is injected into the agent's prompt. Mechanical gathering only (no
# reasoning): the project goal, what shipped this week, our own telemetry, and
# the current backlog so the agent proposes NEW, non-duplicate, on-goal ideas.

set -uo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "$ROOT"

echo "=== WEEKLY RESEARCH CONTEXT (generated $(date -u +%FT%TZ)) ==="
echo
echo "--- PROJECT GOAL (from README.md, top) ---"
sed -n '1,12p' README.md 2>/dev/null
echo

echo "--- SHIPPED IN THE LAST 7 DAYS (merged to main) ---"
git fetch origin --quiet 2>/dev/null || true
git log origin/main --since="7 days ago" --pretty='- %s' 2>/dev/null \
  || git log main --since="7 days ago" --pretty='- %s' 2>/dev/null \
  || echo "(could not read git log)"
echo

echo "--- OUR OWN TELEMETRY (signals to mine for improvements) ---"
# EOD/learning DBs are gitignored (data/); query with the python stdlib sqlite3
# (there is no sqlite3 CLI on this host). Tolerant of missing tables/files.
python3 - <<'PY' 2>/dev/null || echo "(telemetry unavailable)"
import os, sqlite3, glob
cands = ["data/trades.db", "scripts/data/trades.db", "scripts/data/trades_learning.db"]
cands += [p for p in glob.glob("**/*.db", recursive=True) if p not in cands]
seen = set()
for db in cands:
    if db in seen or not os.path.exists(db):
        continue
    seen.add(db)
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        tabs = [r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        parts = []
        for t in tabs:
            try:
                n = con.execute(f"SELECT COUNT(*) FROM \"{t}\"").fetchone()[0]
                parts.append(f"{t}={n}")
            except Exception:
                pass
        print(f"{db}: " + (", ".join(parts) if parts else "(no tables)"))
        con.close()
    except Exception as e:
        print(f"{db}: (unreadable: {e})")
PY
echo "latest baseline: $( [ -f metrics/baseline.json ] && python3 -c "import json;b=json.load(open('metrics/baseline.json'));print('minTests='+str(b.get('minTests','?')))" || echo 'none' )"
echo "latest scan outputs: $(ls -t outputs/*.json 2>/dev/null | head -1 || echo 'none') ($(date -u -r "$(ls -t outputs/*.json 2>/dev/null | head -1)" +%FT%TZ 2>/dev/null || echo 'n/a'))"
echo

echo "--- CURRENT BACKLOG (do NOT duplicate these) ---"
for f in backlog/[0-9]*.md; do
  [ -e "$f" ] || continue
  t="$(grep -m1 -iE '^title:' "$f" | sed -E 's/^[Tt]itle:[[:space:]]*//')"
  [ -z "$t" ] && t="$(grep -m1 -E '^# ' "$f" | sed 's/^# //')"
  echo "$f: ${t:-$(basename "$f")}"
done
echo "proposed (awaiting review): $(ls backlog/proposed/*.md 2>/dev/null | grep -vc '/README\.md$') item(s)"
echo "=== END CONTEXT ==="
