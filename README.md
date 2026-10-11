# pr-review-loop

A Claude Code plugin that turns PR review into a repeatable, self-improving loop.
The review commands share one **5-agent panel** and a **per-repo memory** that
learns from how developers respond — so across an 8-round PR it stops re-raising
things the team already dismissed, and remembers what to keep an eye on.

> It posts to GitLab/GitHub only as a normal reviewer would — inline comments and an
> overview via `/review-pr`. It never overrides your repo's `CLAUDE.md` /
> ADRs — those always win.

---

## Table of contents

- [What you get](#what-you-get)
- [Quick start](#quick-start)
- [How it works (under the hood)](#how-it-works-under-the-hood)
- [Commands](#commands)
- [Stack detection & lens packs](#stack-detection--lens-packs)
- [Loop / automation](#loop--automation)
- [Review memory](#review-memory)
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
| `/review-pr-watch [owner/repo]` | drives `/review-pr` in a loop | auto-review PRs you're requested on |
| `/review-pr-stats` · CLI `review-stats` | your terminal | real token usage + the review scoreboard (approvals, P0/P1, disputes) |

Both review paths run the **same 5-agent panel** and share the **same per-repo memory**.
`/review-pr-watch` is one poll cycle — wrap them in `/loop` to run
continuously. `review-stats` reports what the loop produced.

---

## Quick start

### Option A — marketplace (recommended)

A real, versioned plugin (`claude plugin update` / `list` / `enable`). Same
mechanism from the terminal **or** from inside Claude Code — pick either:

```bash
# terminal (CLI)
claude plugin marketplace add NarekManukyan/pr-review-loop
claude plugin install pr-review-loop@pr-review-loop
```
```
# inside Claude Code (slash commands)
/plugin marketplace add NarekManukyan/pr-review-loop
/plugin install pr-review-loop@pr-review-loop
```

Restart the session — the first start syncs the skills and best-effort installs
`graphify` in the background. Then run **`/review-pr-init`** — a guided
setup that asks which PR platform you use (required) and whether you want
graphify (optional), then connects them and runs the doctor.

`/review-pr-doctor` re-checks setup anytime; nothing has to be done by hand.

Update later: `claude plugin update pr-review-loop` (or `/plugin marketplace update
pr-review-loop`), then restart.

### Option B — one line (global, no marketplace)

Installs into `~/.claude` for the current user — available in **every project**.
Re-run the same line any time to update.

```bash
curl -fsSL https://raw.githubusercontent.com/NarekManukyan/pr-review-loop/main/install-remote.sh | bash
```

Clones the plugin to `~/.pr-review-loop`, then installs commands + skills and
(optionally) `graphify`. Requires `git` + `curl`. Restart Claude Code, then
`/review-pr-init`.

### Option C — from the zip

```bash
unzip pr-review-loop.zip && ./pr-review-loop/install.sh
```

---

## How it works (under the hood)

Every review, whichever command triggers it, runs the same pipeline:

```
trigger ─▶ recall memory ─▶ 5-agent panel ─▶ verify ─▶ report ─▶ deliver ─▶ record memory
             ▲                                                                   │
             └──────────────────────── next round ◀──────────────────────────────┘
```

1. **Recall memory** — before reviewing, the panel loads this repo's past outcomes
   and any human watch items (see [Review memory](#review-memory)). This is
   calibration only; `CLAUDE.md` / ADRs still rank above it.
2. **Resolve the stack** — the shared **`review-core`** engine detects the repo's stack
   and libraries (Flutter BLoC/MobX/Riverpod/Provider, Go/Postgres, NestJS, …) and loads
   the matching **lens pack(s)** on top of stack-agnostic **universal lenses**. Unknown
   stack → universal-only fallback. See [Stack detection & lens packs](#stack-detection--lens-packs).
2b. **Detect stacked chains** — when an MR's target branch is another open MR's source
   branch, they form a chain. The panel prints the map
   (`Stack detected: !41 → … → !53 (10 MRs, tip = …)`) and **asks how the chain merges**:
   **atomic** (lands together) or **piecemeal** (each MR reaches `main` on its own). It
   never guesses — that answer is what makes stack-level review correct. Either way the
   panel then reviews the **cumulative diff at the tip as one unit** rather than
   intermediate states that never reach `main`; piecemeal adds a per-MR build gate
   answering only *"does this MR alone leave `main` compiling?"*. Findings are attributed
   back to the MR that introduced them (`git blame` at the tip → the lowest chain branch
   containing that commit) so every author still gets their own comments, and the stack
   gets **one verdict**. Reviewing a 10-deep chain MR-by-MR produced 18 findings a later
   MR in the same chain had already fixed. MRs targeting `main` with no children are
   independent and keep the per-MR path.
3. **5-agent panel** — five reviewers run in parallel, each applying the universal
   lenses + the loaded stack pack. They run on a **minimal toolset** (`Read/Grep/Glob/Bash`)
   — measured 33% cheaper than general-purpose agents, at no quality cost:
   - **A – architecture & patterns** (layering, DI, state management, atomicity, reachability)
   - **B – correctness & edge cases** (logic, null-safety, races/TOCTOU, idempotency, fail-closed security)
   - **C – performance & quality** (hot-path work, complexity, naming, dead code, observability)
   - **D – build & CI parity** (isolated worktree; mirrors the repo's **real CI** —
     formatter/linter/analyzer incl. build tags; errors are blockers; runs on haiku)
   - **E – seams & blast radius** (the code *outside* the diff: is the new thing wired,
     drained like its siblings, consistent with its neighbours, and what does the
     downstream consumer dedup on?)
3b. **Verify** — before anything is delivered, every finding is **re-located** by its
   verbatim snippet (`relocate-findings.py`: deterministic, corrects drifted line numbers
   and decides inline vs MR-level anchoring up front), then the merged set gets one
   **fact-check** pass (`review-filter` agent on haiku) that may drop only findings the
   code at HEAD proves wrong — never a P0/P1 — and lists every drop in the overview.
   Both stages are adapted from Alibaba's OpenCodeReview.
4. **Report** — findings are merged and de-duplicated (overlapping reviewers become
   one thread with "+1" replies), tagged P0/P1/P2, with a copy-paste fix prompt.
5. **Deliver** — inline comments, an overview, a fix prompt and the platform's own
   review state (`/review-pr`).
6. **Record memory** — findings + how the developer responded are written to a
   committed `.review-memory/` folder, feeding the next round. One **verdict roll-up**
   per reviewed MR×round is recorded alongside them (`kind:"review"` — verdict, head SHA,
   P0/P1/P2 counts, build, conflicts) so `review-stats` can count approvals; roll-ups are
   stats only and are excluded from recall, so they can never suppress a finding.

Two loops sit on top:

- **Next-round loop** — recording feeds recall, so round N+1 is aware of rounds 1…N.
  The next round is kicked off by a PR re-request / new commits.
- **Distill loop** — when a finding keeps getting the same developer verdict, a
  SessionStart nudge suggests promoting it into `CLAUDE.md` / an ADR. A **human**
  makes that change; the bot never edits its own rules.

---

## Stack detection & lens packs

Review knowledge is split into two layers so the same engine works across every stack
without a per-stack fork of the commands:

- **Universal lenses** (`review-core/references/universal-lenses.md`, U1–U14) —
  stack-agnostic principles that hold in any language: check-then-act races, write+event
  atomicity, idempotency on money/events, fail-closed security gates, reachability
  (defined ≠ wired), spec/AC match, test-effectiveness, stale-doc-after-rename, verify at
  HEAD (don't trust `resolved`/stale merge flags), CI parity, complexity, resource
  lifecycle, **sibling parity**, and **lifecycle (started ≠ drained)**.
- **Stack lens packs** (`review-core/references/lenses/*.md`) — the idioms of one stack:
  the concrete shape those principles take (e.g. Go SQL `FOR UPDATE`/CAS, Flutter
  `copyWith` reset, NestJS provider wiring). Loaded only when detected.

A **resolver** detects the base stack from the manifest and the state library from the
dependencies, then composes **base + overlays**:

| Repo | Loads |
|---|---|
| Flutter + BLoC | `_base-flutter` + `flutter-bloc` |
| Flutter + MobX (+ Provider) | `_base-flutter` + `flutter-mobx` (+ `flutter-provider`) |
| Go / Postgres | `go-postgres` |
| NestJS | `nestjs` |
| Unknown (Svelte, Rails, …) | **universal-only fallback** — still a full review |

The repo's own `CLAUDE.md` / ADRs / linter config / `.review-memory` always outrank a
generic pack. `/review-pr-doctor` prints which pack(s) the current repo would load.

**Adding a stack:** drop a file in `review-core/references/lenses/` following
`lenses/README.md`, then add its detection row to `resolver.md`. No command changes —
that's the whole point of the split. Packs shipped today: `go-postgres`, `flutter-bloc`,
`flutter-mobx`, `nestjs` (full); `react`, `flutter-provider`, `flutter-riverpod`,
`python` (stubs — universal lenses still apply).

---

## Commands

### `/review-pr <PR_URL> [--fork]`
Full panel review of one PR, posting inline comments. Detects the review round from
existing PR comments, recalls memory, records outcomes. This is the command a human
runs manually and the one the PR watcher drives.

**Seat modes.** Every seat gets a context packet built in code (changed files, rules,
likely reads, its own lenses) instead of fetching material turn by turn.
- **packet** (default): each seat reads the packet itself. On a two-PR benchmark it
  matched the old panel's results with less than half the tokens and in about half the
  time.
- **`--fork`**: you read the packet once and the seats are forks of the orchestrator, so
  the packet is cached once instead of four times. About 40% cheaper again, at slightly
  lower recall in that benchmark. Good for routine PRs, re-reviews, or two cheap passes
  on an important PR. Needs `CLAUDE_CODE_FORK_SUBAGENT=1`; without it the review says so
  and runs in packet mode.

Make fork a repo's default with `"seat_mode": "fork"` in `.review-memory/config.json`
(`--packet` overrides it for one run).

### `/review-pr-stats`  ·  CLI: `review-stats`

Real token usage + the review scoreboard, **read from disk — nothing estimated**.

```bash
review-stats               # this repo, from any terminal (no Claude Code needed)
review-stats --json        # machine-readable
review-stats --sessions 20 # widen the token window
```

- **token usage** — from Claude Code's own session logs (`~/.claude/projects/<slug>/*.jsonl`).
  The number to watch is **cache hit rate**: high (>90%) means the prompt cache is working
  and content is paid ~once; low means caches keep re-warming.
- **review scoreboard** — from `.review-memory/decisions.jsonl`: reviews (MR × round), MRs,
  rounds, findings, **P0 / P1 + blockers**, **approved vs request-changes (+%)**, the
  dev-verdict split with **% fixed / % disputed**, and the recurring findings ripe to distill.
  The useful one is **% disputed** — it means the reviewers are wrong about *this repo*, so
  `rules.md` / CLAUDE.md needs the fix, not the code.

**What it deliberately does not report: your token savings, or per-reviewer cost.**
Claude Code does not persist subagent turns (verified: zero sidechain turns across every
project log; `subagent_tokens` never reaches disk), so a review's true cost cannot be
attributed and the counterfactual is not measurable. The totals shown are **main-thread
only — a review's real cost is higher**. Rather than invent a number, the command says so.

### `/review-pr-watch [owner/repo]`
One watch cycle for `/review-pr`. Finds PRs where you're a requested reviewer, skips
any already reviewed at their current head commit, and runs the next round on the
rest. See [Loop / automation](#loop--automation).

---

## Review board (optional mod)

`mods/review-board` is a second plugin in this marketplace. It adds a live view of a
review and puts limits in code where prompts weren't enough:

- **Board.** A pane with each seat's progress (tool calls used, findings, time), the
  build gate's result, the running cost and a findings total. A short version shows in
  the status line, and a toast summarizes the run when it ends.
- **Seat budget.** A seat's 16th tool call is refused with "return your findings now";
  reads of its own packet don't count. In the benchmark seats ignored "batch your reads"
  in the prompt; this makes the rule stick. `/review-board budget <n>` changes it.
- **No general-purpose seats.** Spawning a review seat as `general-purpose` is refused.
- **Posting guard.** `/review-board guard on` refuses every `gh`/`glab` call that
  comments, reviews, approves or merges, and GitLab MCP writes: a dry run of
  `/review-pr`. `guard off` lifts it.

It works in the terminal (as a docked pane in the fullscreen layout, inline otherwise)
and in the desktop app. Hooks-module mods are early access in Claude Code right now, so
set `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1` in the `env` block of `~/.claude/settings.json`,
then:

```
/plugin install review-board --marketplace NarekManukyan/pr-review-loop
```

Tests: `CLAUDE_CODE_ENABLE_FUNCTION_HOOKS=1 claude plugin test mods/review-board`.

## Loop / automation

Wrap the watch command in `/loop`:

```
/loop 10m /review-pr-watch                       # inline, PRs you're requested on
/loop 10m /review-pr-watch --fork                # same, cheaper fork-mode seats
```

**How a next round is detected**

State is keyed by `PR number + head commit` in review memory. A
  PR is reviewed **once per head**. The next round fires only when the developer
  **pushes new commits** (head advances) or a **re-request produces a new head**.
  A bare re-request with **no new commits is intentionally skipped** — nothing
  changed to review.

The watcher caps work per cycle (default 3 PRs) so a cycle can't run away; the next
cycle continues. In loop mode the interactive confirmation is skipped — the `/loop`
invocation is the standing authorization — but every other guardrail stays.

> **Tip:** point a new loop at a single test PR for the first day to confirm detection
> behaves before turning it on for real.

**Dry run first.** Validate detection without acting — reports what it *would*
review, but posts and reviews nothing:

```
/review-pr-watch --dry-run
```

**Per-repo config** (`.review-memory/config.json`, committed) tunes the loop without
editing skills — the per-cycle cap, stack, extra generated-file globs:

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

## Guardrails & safety

- **No surprise comments.** Only `/review-pr` writes on GitLab/GitHub, as a normal
  reviewer would; `--dry-run` on the watcher posts nothing.
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

# teammates — terminal
claude plugin update pr-review-loop        # then restart Claude Code

# teammates — inside Claude Code
/plugin marketplace update pr-review-loop
/plugin install pr-review-loop@pr-review-loop
```

---

## Requirements

- **Claude Code** with plugin support.
- **gh** CLI authenticated (GitHub) or **glab** (GitLab).
- **graphify** (optional): semantic review-memory recall; auto-installed best-effort.
- **macOS / Linux** for the hooks and shell scripts. On native Windows, use WSL.

---

## Troubleshooting

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
├── agents/
│   ├── review-panel.md           # reviewer seat A/B/C/E/F (Read/Grep/Glob/Bash only)
│   ├── review-build.md           # Reviewer D — build & CI parity (haiku)
│   └── review-filter.md          # fact-check pass before delivery (haiku)
├── commands/
│   ├── review-pr.md              # /review-pr
│   ├── review-pr-watch.md        # /review-pr-watch
│   ├── review-pr-stats.md        # /review-pr-stats
│   ├── review-pr-init.md         # /review-pr-init (guided setup)
│   └── review-pr-doctor.md       # /review-pr-doctor
├── payload/skills/               # synced to ~/.claude/skills on install/first-run
│   ├── review-core/              # engine: personas, lenses, resolver, verify-findings + relocate-findings.py
│   └── review-memory/            # learning engine (recall/record/note/distill/health/config/doctor)
├── hooks/ensure-and-nudge.sh     # SessionStart: sync skills, install graphify, distill nudge
├── scripts/ensure-graphify.sh    # best-effort graphify installer
├── scripts/attribute-findings.sh # stack mode: finding → introducing MR
├── tests/                        # stdlib unittest (memory recall, relocate, packets, build gate)
├── mods/review-board/            # optional mod: live board + seat budget + posting guard
├── install.sh                    # standalone (no-marketplace) installer
├── CHANGELOG.md
└── README.md
```
