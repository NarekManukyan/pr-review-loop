# pr-review-loop

A Claude Code plugin that turns PR review into a repeatable, self-improving loop.
Three review commands share one 4-agent review panel and a **per-repo memory** that
learns from how developers respond — so across an 8-round PR it stops re-raising
things the team already dismissed, and remembers what to keep an eye on.

> It never posts to GitLab/GitHub on its own except via `/review-pr` (which is a
> normal reviewer posting inline). It never overrides your repo's `CLAUDE.md` /
> ADRs — those always win.

---

## Table of contents

- [What you get](#what-you-get)
- [Quick start](#quick-start)
- [Slack setup](#slack-setup)
- [How it works (under the hood)](#how-it-works-under-the-hood)
- [Commands](#commands)
- [Loop / automation](#loop--automation)
- [Review memory](#review-memory)
- [Reactions = PR state](#reactions--pr-state)
- [Guardrails & safety](#guardrails--safety)
- [Updating (for the team)](#updating-for-the-team)
- [Requirements](#requirements)
- [Troubleshooting](#troubleshooting)
- [Repo layout](#repo-layout)

---

## What you get

| Command | Delivers to | Use it for |
|---|---|---|
| `/review-pr <PR_URL>` | inline comments on the PR | a normal reviewer pass on one PR |
| `/review-pr-slack <PR URLs \| Slack msg URL>` | an HTML report + a short Slack verdict | rich review without touching the PR; team visibility |
| `/review-pr-watch [owner/repo]` | drives `/review-pr` in a loop | auto-review PRs you're requested on |
| `/review-pr-slack-watch #channel` | drives `/review-pr-slack` in a loop | auto-review PRs posted in a channel |

All of them run the **same 4-agent panel** and share the **same per-repo memory**.
The two `*-watch` commands are one poll cycle each — wrap them in `/loop` to run
continuously.

---

## Quick start

### Option A — one-click (marketplace, recommended for teams)

In Claude Code:

```
/plugin marketplace add NarekManukyan/pr-review-loop
/plugin install pr-review-loop@pr-review-loop
```

Restart the session, then run **`/review-pr-init`** — a guided setup that asks
which PR platform you use (required), whether you want Slack delivery and graphify
(both optional), and connects them. It ends by running the doctor to confirm.

`/review-pr-doctor` re-checks setup anytime; nothing has to be done by hand.

### Option B — standalone (no marketplace)

```bash
unzip pr-review-loop.zip && ./pr-review-loop/install.sh
```

This copies the commands + skills into `~/.claude`, installs `shiki` (report
highlighting) and `graphify` (optional). Restart Claude Code.

---

## Slack setup

`/review-pr-init` sets this up interactively — you usually don't need to do it by
hand. It's only needed for `/review-pr-slack` and the Slack watcher (message, report
upload, and reactions post **as you**); `/review-pr` and local reviews work without it.

Two options `/review-pr-init` offers:
- **send-slack skill** (recommended) — posts as you, uploads the HTML report, sets
  reactions. Manual equivalent: `~/.claude/skills/slack-send/install.sh`.
- **Slack MCP connector** — message-only (no file upload, no reactions); enable it
  in your claude.ai connector settings.

---

## How it works (under the hood)

Every review, whichever command triggers it, runs the same pipeline:

```
trigger ─▶ recall memory ─▶ 4-agent panel ─▶ report ─▶ deliver ─▶ record memory
             ▲                                                        │
             └───────────────── next round ◀──────────────────────────┘
```

1. **Recall memory** — before reviewing, the panel loads this repo's past outcomes
   and any human watch items (see [Review memory](#review-memory)). This is
   calibration only; `CLAUDE.md` / ADRs still rank above it.
2. **4-agent panel** — four reviewers run in parallel:
   - **A – architecture & patterns** (layering, DI, state management)
   - **B – correctness & edge cases** (logic, null-safety, races, error handling)
   - **C – performance & quality** (rebuilds, complexity, naming, dead code)
   - **D – build & analyze** (checks out the branch in an isolated worktree,
     compiles + runs the analyzer; errors become blockers, warnings are counted)
3. **Report** — findings are merged and de-duplicated (overlapping reviewers become
   one thread with "+1" replies), tagged P0/P1/P2, with a copy-paste fix prompt.
4. **Deliver** — inline (`/review-pr`) or an HTML report + Slack verdict
   (`/review-pr-slack`).
5. **Record memory** — findings + how the developer responded are written to a
   committed `.review-memory/` folder, feeding the next round.

Two loops sit on top:

- **Next-round loop** — recording feeds recall, so round N+1 is aware of rounds 1…N.
  What *kicks off* the next round differs by surface: a Slack thread reply, or a PR
  re-request / new commits.
- **Distill loop** — when a finding keeps getting the same developer verdict, a
  SessionStart nudge suggests promoting it into `CLAUDE.md` / an ADR. A **human**
  makes that change; the bot never edits its own rules.

---

## Commands

### `/review-pr <PR_URL>`
Full panel review of one PR, posting inline comments. Detects the review round from
existing PR comments, recalls memory, records outcomes. This is the command a human
runs manually and the one the PR watcher drives.

### `/review-pr-slack <PR URLs | Slack message URL>`
Same panel, but **never comments on the PR**. Produces:
- a self-contained **HTML report** — GitHub-style diffs (only commented hunks),
  syntax-highlighted, build status per PR, all findings threaded inline, and fix
  prompts;
- a short **Slack verdict message** — DM to the author, or a reply in the thread if
  you pass a Slack message URL.

Give it a **Slack message URL** and it reads the whole thread, extracts every PR
link, reviews them, and replies the verdict there — the basis for the Slack watcher.

### `/review-pr-watch [owner/repo]`
One watch cycle for `/review-pr`. Finds PRs where you're a requested reviewer, skips
any already reviewed at their current head commit, and runs the next round on the
rest. See [Loop / automation](#loop--automation).

### `/review-pr-slack-watch #channel`
One watch cycle for `/review-pr-slack`. Scans a channel for PR links, reviews new
ones, and picks up next rounds when the author replies. Reactions on each message
track state.

---

## Loop / automation

Wrap a watch command in `/loop`:

```
/loop 10m /review-pr-watch                       # inline, PRs you're requested on
/loop 10m /review-pr-slack-watch #code-review     # Slack, PRs posted in a channel
```

**How a next round is detected**

- **PR watcher** — state is keyed by `PR number + head commit` in review memory. A
  PR is reviewed **once per head**. The next round fires only when the developer
  **pushes new commits** (head advances) or a **re-request produces a new head**.
  A bare re-request with **no new commits is intentionally skipped** — nothing
  changed to review.
- **Slack watcher** — reactions are the state: no reaction = to-do, 👀 = in
  progress, ✅/🔧 = done. A next round fires when the **author replies** in a
  reviewed thread asking to re-review.

Both watchers cap work per cycle (default 3 PRs) so a cycle can't run away; the next
cycle continues. In loop mode the interactive confirmation is skipped — the `/loop`
invocation is the standing authorization — but every other guardrail stays.

> **Tip:** point a new loop at a low-traffic test channel / a single test PR for the
> first day to confirm detection and reactions behave before turning it on your main
> review channel.

**Dry run first.** Validate detection without acting — reports what it *would*
review and which reactions it'd set, but posts and reviews nothing:

```
/review-pr-watch --dry-run
/review-pr-slack-watch #code-review --dry-run
```

**Per-repo config** (`.review-memory/config.json`, committed) tunes the loop without
editing skills — the per-cycle cap, default watch channel, state emojis, stack,
extra generated-file globs:

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py config . --init   # writes an editable default
```

---

## Review memory

A committed `.review-memory/` folder in each repo, written and read by
`skills/review-memory/scripts/memory.py`.

**Why per-repo, not shared:** the same command runs on repos with opposite
architectures (a MobX app and a BLoC app share a language but not their rules). Memory
is keyed to each repo — aligned with that repo's own `CLAUDE.md` + ADRs — and never
shared across repos.

**Authority hierarchy (never inverts):**
1. `CLAUDE.md` + ADRs — authoritative, hand-written.
2. `.review-memory/rules.md` — curated, human-approved distilled rules.
3. `.review-memory/decisions.jsonl` — raw outcome log; calibrates confidence.

Memory only *calibrates* a review — it cuts repeat-noise and honors prior deferrals.
Every finding must still be provable against the current code.

**What it stores & does**

| Action | Command | Effect |
|---|---|---|
| recall | `memory.py recall . --area "<paths>"` | surfaces watch items + prior verdicts before reviewing |
| record | `memory.py record . --input decisions.json` | logs this round's findings + developer responses |
| watch item | `memory.py note . --area "<file>" --text "…"` | a sticky human "check this in future PRs" that resurfaces until closed |
| close | `memory.py close . --signature "<sig>"` | marks a watch item checked |
| distill | `memory.py distill .` | lists recurring findings (candidates to codify) |
| ripe | `memory.py ripe .` | findings with a consistent verdict, ready to codify (used by the nudge) |
| health | `memory.py health .` | review-health report: volume, dispute rate per category (precision), open debt |
| config | `memory.py config . --init` | write/read the per-repo `config.json` |

**Review health.** `memory.py health .` surfaces whether the bot is actually
helping: findings per round, **dispute rate per category** (if e.g. "performance"
findings get disputed 60% of the time, you see it and can down-weight that lane),
open watch items, and deferred-not-closed count. This is also the guard against
feedback drift — you measure precision instead of trusting suppression blindly.

**Watch items** are the "important, don't forget" channel: flag complex logic that
wasn't fully verified and it shows at the top of every future review touching that
area — across PRs, not just rounds — until a human closes it.

**Promotion is human.** Recurring, confirmed lessons get moved into `CLAUDE.md` / a
new ADR via a normal PR. Once codified there, the memory bullet can be removed. The
bot never rewrites its own rules from unreviewed replies.

`graphify`, if installed, adds a semantic recall layer over the corpus; without it,
deterministic JSONL recall works fine.

---

## Reactions = PR state

On the Slack trigger message (`/review-pr-slack` and the Slack watcher):

| Emoji | Meaning |
|---|---|
| 👀 `eyes` | review in progress |
| ✅ `white_check_mark` | approved (all PRs, no P0/P1) |
| 🔧 `wrench` | changes requested (any Request-Changes / broken build / open P0-P1) |

This doubles as the Slack watcher's state machine — it reads the reactions and never
reviews the same message twice.

---

## Guardrails & safety

- **No surprise comments.** `/review-pr-slack` and both watchers never write on
  GitLab/GitHub. `/review-pr` posts inline — that's a normal reviewer action.
- **FACT vs ASSUMPTION.** Only findings provable from the code are posted; the rest
  become questions.
- **Generated files skipped** (`*.g.dart`, `*.freezed.dart`, lockfiles, etc.; extends
  from the repo's `CLAUDE.md`).
- **Per-cycle caps** on loops; interactive confirmation only skipped inside `/loop`.
- **Memory never overrides `CLAUDE.md`/ADRs** and never self-edits its rules.

---

## Updating (for the team)

You ship an improvement once; teammates pull it:

```bash
# maintainer
cd <plugin checkout> && git add -A && git commit -m "…" && git push

# teammates, in Claude Code
/plugin marketplace update pr-review-loop
/plugin install pr-review-loop@pr-review-loop
```

---

## Requirements

- **Claude Code** with plugin support.
- **gh** CLI authenticated (GitHub) or **glab** (GitLab).
- **Slack**: the sender token (`slack-send/install.sh`) — only for the Slack command
  and watcher.
- **node + npm** (optional): bakes syntax highlighting into the HTML report; without
  it the report falls back to CDN highlighting (fine in a browser, not in Slack's
  preview).
- **graphify** (optional): semantic review-memory recall; auto-installed best-effort.
- **macOS / Linux** for the hooks and shell scripts. On native Windows, use WSL.

---

## Troubleshooting

- **`/review-pr-slack` can't post** → run `~/.claude/skills/slack-send/install.sh` to
  connect the token.
- **Report isn't highlighted in Slack preview** → `node`/`npm` missing at install
  time; re-run the installer, or open the HTML in a browser.
- **graphify not installed** → harmless; JSONL recall still works. Retry with
  `~/.claude/skills/.../scripts/ensure-graphify.sh --force` (or `pipx install graphifyy`).
- **Watcher re-reviews nothing** → check `gh auth status` / `glab auth status`, and
  that you're actually a requested reviewer on an open PR.
- **Nudge never appears** → it only fires when a finding has recurred with a
  consistent verdict; run `memory.py distill .` to see candidates manually.

---

## Repo layout

```
pr-review-loop/
├── .claude-plugin/{plugin,marketplace}.json   # manifests (repo is its own marketplace)
├── commands/
│   ├── review-pr.md              # /review-pr
│   ├── review-pr-watch.md        # /review-pr-watch
│   ├── review-pr-slack-watch.md  # /review-pr-slack-watch
│   ├── review-pr-init.md         # /review-pr-init (guided setup)
│   └── review-pr-doctor.md       # /review-pr-doctor
├── payload/skills/               # synced to ~/.claude/skills on install/first-run
│   ├── review-memory/            # learning engine (recall/record/note/distill/health/config/doctor)
│   ├── review-pr-slack/          # panel → HTML report + Slack verdict
│   └── slack-send/               # msg / report upload / reactions / channel watch
├── hooks/ensure-and-nudge.sh     # SessionStart: sync skills, install graphify, distill nudge
├── scripts/ensure-graphify.sh    # best-effort graphify installer
├── install.sh                    # standalone (no-marketplace) installer
├── CHANGELOG.md
└── README.md
```
