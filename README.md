# pr-review-loop — Claude Code plugin

A PR review toolkit + a **self-improving per-repo review memory**, packaged as a
one-click Claude Code plugin for the team.

**Commands**

- **`/review-pr <PR_URL>`** — 3-persona senior-engineer review panel
  (Architecture / Correctness · Edge Cases / Performance · Quality) with
  FACT-vs-ASSUMPTION discipline, ADR citations, and a copy-paste fix prompt. Posts
  inline (this repo).
- **`/review-pr-slack <PR URLs | Slack message URL>`** — same panel, delivered as
  a self-contained **HTML report** (highlighted diffs, only commented hunks, build
  status, fix prompts) + a short **verdict message** posted to Slack. Never
  comments on GitLab/GitHub. Give it a Slack message URL and it reads the thread,
  extracts the PR links, and replies the verdict there.
- **`/review-pr-watch [owner/repo]`** — one watch cycle for `/review-pr`: finds
  PRs where you're a requested reviewer or whose head advanced since your last
  review, and runs the next round. Wrap in `/loop`.
- **`/review-pr-slack-watch #channel`** — one watch cycle for `/review-pr-slack`;
  wrap in `/loop` to run continuously (see **Loop mode**).

**Reactions = PR state.** On the trigger message: 👀 review in progress →
✅ approved / 🔧 changes requested. This doubles as the loop's state machine, so
the watcher needs no external database.

- **review-memory** — after each review the panel records findings + how
  developers responded (resolved / deferred / disputed / clarified) into a
  committed `.review-memory/` folder in the repo, and recalls them next round so
  it stops re-raising dismissed findings and checks that deferred fixes landed.
  Humans can also drop **sticky watch items** (`memory.py note`) — "verify this
  complex logic in future PRs" — that resurface in every future review of that
  area until closed.
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
/plugin install pr-review-loop@pr-review-loop
```

Updates later: `/plugin marketplace update pr-review-loop` then reinstall. Everyone
tracks the same version; you ship an improvement once and the team gets it.

## Install — standalone (no marketplace)

```bash
unzip pr-review-loop.zip && ./pr-review-loop/install.sh
```

Restart Claude Code. (The SessionStart auto-nudge only runs in the marketplace
install; standalone users run `distill` by hand — see below.)

## Prerequisites

- **gh** CLI authenticated (or **glab** for GitLab).
- **graphify** — adds a semantic recall layer over the memory corpus. The
  installer (and, for marketplace installs, a one-time background step on first
  session) **auto-installs it** best-effort via uv / pipx / pip. If it can't be
  installed on a given machine, deterministic JSONL recall still works — nothing
  breaks. Marker file `~/.claude/.pr-review-loop-graphify-checked` stops retries;
  delete it (or run `scripts/ensure-graphify.sh --force`) to retry.

## Slack setup (for /review-pr-slack and the watcher)

The Slack verdict message, report upload, and reactions post as you via a sender
token — connect it once:

```bash
~/.claude/skills/slack-send/install.sh
```

Without it, review still works locally; only the Slack delivery/reactions need the token.

## Loop mode

Run the watcher continuously over a channel — reactions are the state (unreacted
PR = to-do, 👀 = in progress, ✅/🔧 = done), so it never re-reviews the same thing:

**Slack channel** (report + verdict delivery):
```
/loop 10m /review-pr-slack-watch #your-review-channel
```
Each cycle: reviews **new** PRs (message with a PR URL and no state reaction), and
picks up **next rounds** (a reviewed PR whose author replied asking to re-review —
the thread replies feed the re-review and memory recall applies).

**Inline PR review** (posts on the PR itself):
```
/loop 10m /review-pr-watch
```
Each cycle: finds PRs where you're a requested reviewer, skips any already reviewed
at their current head, and runs the next round on the rest. A **next round fires
automatically** when the developer pushes new commits or re-requests review — the
head advances, so the PR is no longer "reviewed at this head". State is keyed by
PR + head commit in review memory, so nothing is reviewed twice.

Both are capped per cycle so they can't run away. In loop mode the interactive
confirmation is skipped (the `/loop` is the standing authorization); all other
guardrails stay.

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
pr-review-loop/
├── .claude-plugin/
│   ├── plugin.json         # plugin manifest + SessionStart hook
│   └── marketplace.json    # makes this repo its own marketplace
├── commands/review-pr.md   # the /review-pr panel command
├── skills/review-memory/   # the learning engine (recall/record/distill/ripe)
├── hooks/ensure-and-nudge.sh
├── install.sh              # standalone (no-marketplace) installer
└── README.md
```
