# mone-review — Claude Code plugin

`/review-pr` panel review + a **self-improving per-repo review memory**, packaged
as a one-click Claude Code plugin for the team.

- **`/review-pr <PR_URL>`** — a 3-persona senior-engineer review panel
  (Architecture / Correctness · Edge Cases / Performance · Quality) with
  FACT-vs-ASSUMPTION discipline, ADR citations, and a copy-paste fix prompt.
- **review-memory** — after each review the panel records findings + how
  developers responded (resolved / deferred / disputed / clarified) into a
  committed `.review-memory/` folder in the repo, and recalls them next round so
  it stops re-raising dismissed findings and checks that deferred fixes landed.
- **Auto-improvement, safely** — a SessionStart hook surfaces findings that keep
  getting the same developer verdict and nudges you to codify them into
  CLAUDE.md / an ADR. Recording and recall are automatic; **promoting a rule is a
  human decision** — the bot never rewrites its own rules from unreviewed replies.
  Memory never overrides CLAUDE.md / ADRs.

## Install — one click (marketplace)

Push this folder to a git repo your team can reach (it is its own marketplace —
`.claude-plugin/marketplace.json` is included), then each teammate runs, in
Claude Code:

```
/plugin marketplace add <your-org>/<repo>
/plugin install mone-review@mone-review
```

Updates later: `/plugin marketplace update mone-review` then reinstall. Everyone
tracks the same version; you ship an improvement once and the team gets it.

## Install — standalone (no marketplace)

```bash
unzip mone-review.zip && ./mone-review/install.sh
```

Restart Claude Code. (The SessionStart auto-nudge only runs in the marketplace
install; standalone users run `distill` by hand — see below.)

## Prerequisites

- **gh** CLI authenticated (or **glab** for GitLab).
- **graphify** — adds a semantic recall layer over the memory corpus. The
  installer (and, for marketplace installs, a one-time background step on first
  session) **auto-installs it** best-effort via uv / pipx / pip. If it can't be
  installed on a given machine, deterministic JSONL recall still works — nothing
  breaks. Marker file `~/.claude/.mone-review-graphify-checked` stops retries;
  delete it (or run `scripts/ensure-graphify.sh --force`) to retry.

## Why per-repo memory (not shared)

The same command runs on different repos with different architectures — a MobX
Flutter app and a BLoC Flutter app share a language but oppose each other's rules.
Memory is therefore keyed to each repo's `.review-memory/` folder, aligned with
that repo's own CLAUDE.md + ADRs, and never shared across repos. It only
*calibrates* a review; every finding must still be provable against current code.

## Promoting lessons (the human step)

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py distill .   # candidates
python3 ~/.claude/skills/review-memory/scripts/memory.py ripe .      # ready-to-codify
```

Move a confirmed lesson into CLAUDE.md / a new ADR via a normal PR. Once codified
there, its `.review-memory/rules.md` bullet can be removed.

## Contents

```
mone-review/
├── .claude-plugin/
│   ├── plugin.json         # plugin manifest + SessionStart hook
│   └── marketplace.json    # makes this repo its own marketplace
├── commands/review-pr.md   # the /review-pr panel command
├── skills/review-memory/   # the learning engine (recall/record/distill/ripe)
├── hooks/ensure-and-nudge.sh
├── install.sh              # standalone (no-marketplace) installer
└── README.md
```
