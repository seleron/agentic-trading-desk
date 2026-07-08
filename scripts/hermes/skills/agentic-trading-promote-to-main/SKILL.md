---
name: agentic-trading-promote-to-main
description: "Promote the agentic-trading-desk loop branch (autonomous/scaffolding) to main — the weekly production merge. Trigger when the user says 'merge trading to main', 'promote trading to main', 'ship trading scaffolding to main', or similar for the agentic-trading-desk project."
version: 1.0.0
platforms: [linux, macos, windows]
metadata:
  hermes:
    tags: [trading, git, deploy, promote, merge, main]
    related_skills: []
---

# agentic-trading-desk — Promote scaffolding → main

## When to use
The user says "merge trading to main", "promote trading to main", "ship trading
scaffolding to main", or similar, about the agentic-trading-desk. This is the
weekly production merge, after the change set has been validated for a week.

## What to do
There is **no code review at this stage** — each change set was already reviewed
and gated when it merged to `autonomous/scaffolding`, so do NOT re-review it. Just
run the promote script and report the result. The script merges
`autonomous/scaffolding` → `main` in an isolated worktree (the live loop checkout
is untouched), runs the deterministic gate (`scripts/ci.sh`) as a safety check,
and pushes `main`.

Run exactly this (no edits, no extra git commands):

    bash __TRADING_REPO__/scripts/hermes/promote-to-main.sh

Then report its final line verbatim. Interpret it:
- `✅ Promoted …`          → success. `main` now carries the week's work.
- `✅ Nothing to promote …` → main is already current; nothing to do.
- `⛔ …`                    → it stopped **safely** (gate failed, merge conflict,
  or push failed). Relay the exact reason — a human needs to look. Do NOT retry
  forcefully or edit `main` by hand.

Never push to `main` directly or bypass the script.
