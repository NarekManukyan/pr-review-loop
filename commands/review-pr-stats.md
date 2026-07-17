---
description: Show real token usage and review activity for this repo — read from Claude Code's own logs and .review-memory, never estimated.
argument-hint: [--sessions N] [--json]
---

Run the stats script and interpret it for the user:

```bash
python3 ~/.claude/skills/review-memory/scripts/stats.py . $ARGUMENTS
```

Everything it prints is **read from disk** — Claude Code's session logs
(`~/.claude/projects/<slug>/*.jsonl`) and this repo's
`.review-memory/decisions.jsonl`. **Do not add numbers of your own, do not
estimate, and do not compute "savings"** — the caveats below are the reason.

## Interpreting it for the user

**token usage** — `effective input` applies the published cache ratios
(read ×0.10, write ×1.25) so sessions are comparable; it is *not* a bill. The
number that usually matters is **cache hit rate**: high (>90%) means the prompt
cache is doing its job and content is being paid for roughly once. A low rate
means caches keep re-warming (long gaps between turns, or a churning prefix) —
that is the one thing here the user can actually act on.

**review activity** — the plugin's value story: MRs reviewed, rounds, findings by
severity, and what the developers actually did with them
(`resolved` / `deferred` / `disputed` / `open`). A high `disputed` count means the
reviewers are wrong about something in this repo — check `.review-memory/rules.md`
and CLAUDE.md. The **recurring** list is the distill queue: findings raised more
than once are ripe to promote into CLAUDE.md or an ADR by a human
(`memory.py distill .`). Nothing auto-edits.

**engine efficiency** — measured constants from the v1.10.0 probes, printed as
reference, *not* as a measurement of this user's runs. Say so if you quote them.

## What this CANNOT show (say it plainly if asked)

- **Per-reviewer cost.** Claude Code does not log subagent turns — verified: zero
  sidechain turns across every project log, and `subagent_tokens` is never
  persisted. The token totals are **main-thread only**, so a review's real cost is
  *higher* than shown and cannot be attributed to a reviewer, a model tier, or a
  round.
- **Your savings.** We cannot measure the counterfactual (what the same review
  would have cost as `general-purpose`), so the command does not pretend to. The
  83% / 33% figures are from controlled probes, not from your history.
- **Plan limits / quota.** Not exposed to the plugin by any API we can read.

If the user wants savings analytics in the `rtk gain` sense, be honest: the data
to compute it per-run does not exist on disk today. What we have is the measured
constant and the real main-thread usage.

## Output

Lead with the two numbers that mean something — **cache hit rate** and **dev
verdicts** — then the distill queue if it is non-empty. Keep it short; the script's
own output is already the report.
