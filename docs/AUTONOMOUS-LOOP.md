# Autonomous PR Review Loop

## The Flow

```
┌──────────────┐     ┌───────────────────┐     ┌──────────────────┐
│  Feature      │     │ Nightly Improve   │     │ Claude Review    │
│  Request      │────▶│ (picks top item)  │────▶│ (pr-review.sh)   │
│  (manual or   │     └───────────────────┘     └────────┬─────────┘
│   weekly       │                                         │
│   research)    │                    REQUEST_CHANGES      │ APPROVE
│                │                       ▼                 │         ▼
│  backlog/NNN   │            ┌──────────────┐   ┌───────────┐  ┌──────────┐
│  item created  │            │ Implementer  │   │ Auto-    │  │ Higher-  │
│                │◀───────────│ (nightly     │   │ merge    │  │ risk →   │
│                │            │  cron)       │   │ +        │  │ mark     │
└──────────────┘            └──────────────┘   │ reconcile│  │ ready    │
                                                └──────────┘  └──────────┘
```

## Step-by-Step

### 1. Feature Request
- Manual: You tell Claude to build something → creates `backlog/NNN-feature.md` with Rank N
- Weekly Research: Cron picks up research findings → creates backlog items

### 2. Nightly Improve Picks Up Task
The cron job (`52950f8186af`) runs at 3 AM daily (or dispatched immediately after a review). It:
- Reads `loop-context.sh` which generates prioritized candidate list
- **Rank 0**: Review-fix items (Claude requested changes on open PR)
- **Ranked N**: Feature items sorted by rank ascending
- Skips any item with `✅ RESOLVED` in its content

### 3. Claude Reviews Implementation
`pr-review.sh <PR-NUMBER>` is called, which:
1. Runs independent gate (tests restored from base branch)
2. Computes deterministic risk signals
3. Sends diff + signals to Claude Opus 4.8 for review
4. Claude outputs JSON with decision, fixes list, and merge safety

### 4a. REQUEST_CHANGES → Auto-Fix Cycle
1. **Fix-awareness**: Checks if requested fixes were already addressed (commit messages + file content + recent diffs)
2. **Files fix item** to `backlog/NNN-fix-prX.md` with:
   - Explicit PR number and branch name
   - Code-level instructions for each fix
   - Acceptance criteria (tests must pass, no regressions)
3. **Dispatches nightly improve immediately** (doesn't wait for 3 AM)

### 4b. IMPLEMENTER Applies Fixes
The implementer cron job:
1. Reads the highest-priority fix item
2. Checks out the PR branch (`Branch:` header in the item)
3. Fetches latest, rebases if needed
4. Makes code changes matching "Required fixes"
5. Runs tests — fixes any failures
6. Commits with descriptive message matching fix keywords (helps Claude's fix-awareness next round)
7. Pushes to remote

### 4c. RE-REVIEW Loop
The review poll (every 30m) picks up the new commits and re-runs Claude review:
- If **REQUEST_CHANGES** again → goes back to step 4a (but fix-awareness filters addressed items)
- If **APPROVE** → goes to merge path

### 5. Merge + Auto-Reconcile
- **Low-risk + gate green**: Auto-merge with squash, then call `backlog-reconcile.sh`
- **Higher-risk**: Mark PR ready for human merge
- **Reconciliation**: Scans all backlog items for matches to merged PR → marks them ✅ RESOLVED

## Reconciliation Details

`backlog-reconcile.sh` runs:
1. After every auto-merge (from pr-review.sh)
2. On every health check run (catches human merges)
3. Matches against: `PR:` header, `Resolves-Backlog:` marker, filename patterns like `fix-prX.md`, and body references to PR numbers

## Fix-Awareness Rules

Claude's fix-awareness checks THREE things before requesting a fix:
1. **Commit messages** on the PR branch (keyword match)
2. **File content** in current diff (function/variable names present?)
3. **Recent commit diffs** (`git show` for last 5 commits)

If any check passes, the fix is considered addressed and Claude won't re-request it.

## Backlog Item Format

```markdown
# Address Claude review on PR #X
Area: review-fix
Rank: 1
PR: #X
Branch: feature/branch-name
Base Branch: main
Resolves-Backlog: fix-prX
Claude-Round: N

## Why
Claude Opus 4.8 requested changes...

## Required fixes
- Fix description with code-level detail
- Another fix...

## Acceptance
- Unit tests pass
- No regressions

## Constraints
- UPDATE the existing branch (do NOT open a new PR)
```
