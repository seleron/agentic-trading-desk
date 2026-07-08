# Autonomous Improvement Loop

A self-driving develop → review → fix → ship loop for this repo, mirroring the
Adverts-Project loop and adapted to a Python / `unittest` / no-Docker project.
It runs under **Hermes** cron jobs and uses **Claude Opus 4.8** as the reviewer.

## The flow

```
 feature request                nightly improve                 Claude review
 (you drop a         ─────▶      (implements the      ─────▶     (pr-review.sh:
  backlog/NNN item,               lowest-rank item on             trusted gate +
  or weekly research              an isolated worktree,           holistic diff review)
  proposes one)                   opens a DRAFT PR
                                  auto/<slug> → scaffolding)            │
        ▲                                                              │
        │                          REQUEST_CHANGES                     │ APPROVE
        │                                │                             │
        │                                ▼                             ▼
   next nightly  ◀── files rank-0   ┌──────────────┐          ┌──────────────────────┐
   picks up the      fix item +     │ implementer   │          │ low-risk → auto-merge │
   rank-0 fix        dispatches     │ updates the   │          │  (squash) → scaffolding│
   (round-trips      implementer    │ SAME PR branch│          │ high-risk → mark ready │
    until clean)                    └──────────────┘          │  + notify you to merge │
                                                               └──────────────────────┘
                                                                          │
                                                        weekly Sunday you say
                                                        "merge trading to main"
                                                                          ▼
                                                            promote-to-main.sh
                                                        (gate-checked scaffolding → main)
```

**Base branch:** the loop lives on `autonomous/scaffolding`. Nightly branches
`auto/<slug>` **from** it and opens PRs **against** it — never `main`. Approved
low-risk PRs auto-merge to scaffolding; `main` only advances via the weekly,
gate-checked `promote-to-main.sh`.

## Step-by-step

### 1. Feature request
- **Manual:** drop a `backlog/NNN-slug.md` with `rank: <N>` (lower = higher priority).
- **Weekly research:** the Monday cron researches comparable projects + mines our
  telemetry, drafts `backlog/proposed/*.md`, then **Claude approves/ranks** them
  (`weekly-review.sh`) and delivers patch notes. Only approved items enter the
  ranked backlog — proposals are never implemented directly.

### 2. Nightly improve
`loop-context.sh` (a no-LLM preprocessor) reconciles merged PRs, then selects the
single lowest-`rank` open item in `backlog/[0-9]*.md` (review-fix items carry
`rank: 0`, so they always win). The implementer builds it in an isolated worktree,
proves it with the gate, and opens a **draft** PR. It never merges.

### 3. Claude review (`pr-review.sh`)
Triggered every 30 min by `pr-review-poll.sh` (dedup by `PR#:sha`). For each new
HEAD it:
1. Re-runs the **trusted gate** in a throwaway worktree, after restoring
   `scripts/ci.sh` + `metrics/baseline.json` + every `scripts/test_*.py` from the
   base branch — so a PR can't tamper the gate or weaken tests to pass.
2. Computes deterministic risk signals (gate/test edits, sensitive files, size).
3. Asks Claude Opus 4.8 for a holistic verdict: **APPROVE / REQUEST_CHANGES /
   NEEDS_HUMAN** (VERIFY PREMISES, NO HALF-ASSED solutions).

### 4. REQUEST_CHANGES → auto-fix round
Files a **rank-0** `backlog/NNN-fix-prX.md` on the base branch (names the PR
branch to UPDATE + concrete fixes) and **dispatches the implementer immediately**.
The implementer reuses the existing PR branch (no new PR). The 30-min poll sees the
new sha and re-reviews → back to step 3. After `PR_REVIEW_MAX_ROUNDS` (default 8)
unresolved rounds it escalates to a human and pauses.

### 5. APPROVE → merge
- **Low-risk + gate green + no tamper:** auto-merge (squash) to scaffolding, then
  `backlog-reconcile.sh` deletes the resolved backlog item(s).
- **Higher-risk:** mark ready + Telegram-notify you to merge.
- **NEEDS_HUMAN:** post the blocking questions, pause auto-fix; answer in a PR
  comment and the next review run picks it up.

### 6. Weekly promote → main
Sunday 19:30 a reminder shows what's pending. Reply **"merge trading to main"** and
the promote skill runs `promote-to-main.sh`, which merges scaffolding → main in an
isolated worktree, runs the gate as a safety check, and pushes main (or stops
safely with a `⛔` reason).

## The gate — `scripts/ci.sh`

Deterministic, no LLM, same input → same verdict:
1. **Syntax** — `compileall` over `scripts/`.
2. **Unit tests** — `unittest discover` must end `OK`.
3. **Test-count ratchet** — count must be ≥ `metrics/baseline.json:minTests`
   (you can't delete/weaken tests to pass; add tests and bump `minTests`).
4. **Functional smoke** — score a synthetic quote end-to-end, assert `0 ≤ score ≤ 100`.

## Cron jobs (registered by `scripts/hermes/setup-routines.sh`)

| Name | Schedule | State | Purpose |
|------|----------|-------|---------|
| agentic-trading health watch | hourly | ACTIVE | no-LLM loop watchdog (origin/gh reachable, stuck PRs, reconcile) |
| agentic-trading pr review | every 30m | ACTIVE | poll → Claude Opus 4.8 reviews auto/* PRs |
| agentic-trading promote reminder | Sun 19:30 | ACTIVE | nudge to promote scaffolding → main |
| agentic-trading nightly improve | 03:00 daily | PAUSED | implement the top backlog item → draft PR |
| agentic-trading weekly research | Mon 07:00 | PAUSED | research + propose → Claude approves/ranks |

The two agent jobs start **paused**; resume them after a supervised first run.

## Backlog item format

```markdown
---
rank: 3            # lower = higher priority; review-fix items use rank: 0
title: <short title>
area: <scoring|indicators|risk|data|backtest|learning|reporting|devex|review-fix>
depends_on: []
---
# <Title>
## Why ...
## Acceptance ...   # how the gate proves it (new unittests / metrics)
## Constraints ...  # anti-drift reminders
## Notes ...        # pointers into the code
```

An item is removed when its PR merges (via the `Resolves-Backlog:` marker the PR
body carries, a `PR: #N` field, or a "backlog item NNN" reference). Do not hand-
mark items done — `backlog-reconcile.sh` deletes them on merge.

## Scripts (`scripts/hermes/`)

| Script | Role |
|--------|------|
| `lib-loop.sh` | shared git-mutex (`flock`) so loop steps never clobber the checkout |
| `loop-context.sh` | nightly preprocessor: reconcile + select top item + gate info |
| `pr-review-poll.sh` → `pr-review-dispatch.sh` → `pr-review.sh` | the review pipeline |
| `backlog-reconcile.sh` | delete backlog items resolved by merged PRs |
| `worktree-create.sh` / `worktree-setup.sh` / `worktree-remove.sh` | isolated worktrees |
| `research-context.sh` + `PROMPT-weekly-research.md` | weekly research inputs/prompt |
| `weekly-review.sh` | Claude approves/ranks proposals + patch notes |
| `health-watch.sh` | hourly no-LLM loop watchdog |
| `sunday-promote-reminder.sh` / `promote-to-main.sh` | weekly promote to main |
| `setup-routines.sh` | (re)register all crons + install the promote skill |
| `loop.env` (gitignored) | `HERMES_DELIVER=telegram:<chat_id>` delivery target |
```
