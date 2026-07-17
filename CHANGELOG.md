# Changelog

All notable changes to pr-review-loop. Teammates: after a maintainer pushes, run
`/plugin marketplace update pr-review-loop` then reinstall to get the latest.

## 1.12.1

Added
- **`review-stats` CLI — the stats work from any terminal**, not just inside Claude Code
  (`review-stats`, `review-stats --json`, `review-stats ~/code/foo`). Claude Code puts a
  plugin's `bin/` on PATH automatically, but that only applies *inside* Claude Code — a
  real terminal never sees it — so `install.sh` also links the wrapper into
  `~/.local/bin` and warns if that is not on your PATH.

Docs
- README documents `/review-pr-stats` + the `review-stats` CLI, what the metrics mean
  (and that **% disputed** is the one worth watching), the verdict roll-ups, and —
  explicitly — that savings and per-reviewer cost are **not** reported because Claude Code
  does not persist subagent turns.

## 1.12.0

Added
- **Verdict roll-ups — reviews, approvals and blockers are now countable.** The panel
  computed a verdict into `meta.json` every round and then threw it away, so
  "how many were approved?" was unanswerable from disk. `memory.py record` now accepts a
  `reviews` array — one roll-up per reviewed `(mr, round)`:
  `{mr, round, verdict, head_sha, p0, p1, p2, build, conflicts}` — stored as
  `kind:"review"`. Both front-ends emit it.
  **Roll-ups are stats, never findings**: they carry no signature and are explicitly
  excluded from `recall`, so they can never suppress or re-raise a real finding
  (asserted: a resolved finding still surfaces while the roll-up stays out).
- **`/review-pr-stats` now reports the review scoreboard**: reviews (MR x round), MRs,
  rounds, findings, **P0 / P1 and total blockers**, **approved vs request-changes (+ %)**,
  the dev-verdict split with **% fixed** and **% disputed** (a high dispute rate means the
  reviewers are wrong about this repo — check `rules.md`/CLAUDE.md), and the recurring
  findings ripe to distill.
  Reviews/MRs/rounds/P0/P1 are derivable from existing corpora and work retroactively;
  verdict counts start accruing on the next recorded review.

## 1.11.0

Added
- **`/review-pr-stats`** — real token usage + review activity, read from disk, never
  estimated. Token figures come from Claude Code's own session logs
  (`~/.claude/projects/<slug>/*.jsonl`: `input_tokens`, `output_tokens`,
  `cache_read_input_tokens`, `cache_creation_input_tokens`); review figures from this
  repo's `.review-memory/decisions.jsonl` (MRs, rounds, severity split, developer
  verdicts, and the recurring findings that are ripe to distill into CLAUDE.md/an ADR).
  `--json` for scripting.
  **Deliberately does NOT report savings or per-reviewer cost.** Claude Code does not log
  subagent turns — verified: 0 sidechain turns across 49k+ logged turns, and
  `subagent_tokens` is never persisted — so a review's true cost cannot be attributed,
  and the counterfactual ("what would general-purpose have cost?") is not measurable from
  disk. The command states this rather than inventing a number. The v1.10.0 probe
  constants are printed as labelled reference only.
  Incidentally confirms the v1.10.0 cache finding on real data: of 245.9M input tokens in
  a heavy session, **99.999% were cache reads** — content really is paid ~once.

## 1.10.0

The measured token fix, plus the seams reviewer. Four controlled probes (identical work,
one variable each) produced a cost law that fits within 1.4%:

```
cost ~= tool_uses x (system prompt + TOOL SCHEMAS)  +  content (paid ONCE, cached)
                     `- ~6,451/turn, of which ~5,420 is schemas -'
```

Content is cached and paid once, so trimming what reviewers read is NOT where cost lives.
The cost is tool schemas. This release ships only what that finding supports.

Changed
- **Reviewers now spawn as purpose-built agents with a minimal toolset** — new
  `agents/review-panel.md` (A/B/C/E: `Read, Grep, Glob, Bash`) and `agents/review-build.md`
  (D: `Bash, Read`, `model: haiku`), installed to `~/.claude/agents/`. They were
  `general-purpose`, re-sending **~100 unused MCP tool schemas every turn**.
  **Probe**: identical trivial 11-turn agent = **71,479 tok general-purpose vs 12,379 as
  `review-panel` (−82.7%)**. A 4-tool agent with a *longer* system prompt cost only +522
  over a terse one, ruling out prompt length — it is the schemas.
  **Real review** (explorer-back!71, same contract, same 25 tool_uses, only the agent type
  differing): **154,347 → 102,782 (−33% on one reviewer)**, ~258k/round across the panel.
  33% rather than 83% because a real review also carries ~70k of content that does not
  move. **Quality held or improved**: the cheap panel recovered two findings the expensive
  one missed, upgraded the `Update()` TOCTOU to P0, and found a P1 **fail-open** neither
  other arm caught (`explorer.go:636` self-activates an `admin_rejected` guide with the
  gate off, nulling the reason — a branch no test covers).
- **Generated files are skipped from the diff AND from reads, per the loaded pack.** The
  skip list was Flutter-shaped, so Go generated output sailed through: the pack said
  `*.sql.go`, but sqlc also emits `models.go`/`db.go`/`querier.go`, and `docs/swagger/**`
  was unlisted. Measured on explorer-back!71: generated files were **68% of the source
  fetched and 29% of the diff** (64k swagger + 30k sqlc). Free, zero risk.
- **Reviewer D is mechanical again** — CI parity (U10) only, on haiku, small context
  (branch + CI config + file list). Its output is bounded: quote only cited error lines,
  count warnings, truncate dumps over ~50 lines.
- Material caps, stated not silent: skip a file whose diff exceeds ~15k tokens, cap total
  ~60k, and **name every skipped file** in the overview, `meta.json` (`skipped_files`) and
  the verdict. A skipped file is a *known gap*, not a covered one.

Added
- **Reviewer E — Seams & Blast Radius.** Owns **U5** (reachability), **U13** (sibling
  parity), **U14** (lifecycle) and **U3's cross-service consumer contract** — lenses that
  were scattered across A and D, so nobody owned them and nobody looked. One job: *the diff
  changed something — what unchanged code did it just make wrong?* **Validated on
  explorer-back!71**: E found `di/providers.go:166` — the two new subscribers skip the
  `processedEvents` dedup ledger all five siblings on the same subscription use — which the
  old panel missed entirely.
- The mandatory-read rules in `personas.md` § "Reading the code" (whole file for a
  design-system sweep, whole function for a complexity metric, the sibling for U13, the
  composition root for U5/U14). On booking-front!27 these took the panel from **8 findings
  to 25**, recovering the design-system class the old prompts dropped.

Falsified by the probes (recorded so it is not re-attempted)
- **"Bulk-loading full sources costs 3–6x."** Bulk-load != bulk-read: an agent's context
  only grows when it `Read`s. Arm A never opened 104k of the 140k fetched.
- **"Read-on-demand cuts tokens."** It does not — the panel read 92% of sources anyway on
  one MR, and *more* files on another. Agents read what the lenses require. The material
  contract is therefore UNCHANGED in this release; that experiment is still open.
- **"Batching tool calls saves tokens."** It does not — cost scales with tool-*uses*, not
  API round-trips (71,687 batched vs 71,479 serial). ~3x latency win only.
- **"Re-sent context dominates."** It is cached: +24.9k of content cost +24.9k once, not x10.

## 1.9.0

Review the blast radius, not just the diff. From a gap analysis against
`dz44-group/bookings/booking-back!31`: our panel found 11 real findings across two
rounds, then a human found four more that were present in the exact tree we reviewed.
Three of the four lived in the **seams the change touches** — the unchanged composition
root, a sibling endpoint, and the consumer on the far side of the outbox. The panel was
anchoring on changed lines.

Added
- **U13 — Sibling parity.** Every new endpoint/worker/handler/subscriber/provider is
  compared against its nearest existing sibling of the same class in the same file or
  package; each divergence (required headers, auth, error→status mapping, registration,
  timeout/retry, logging) is justified or a finding. A U13 finding **must cite the
  sibling's `file:line`** next to the new code's. Caught: a new cancel POST missing the
  `Idempotency-Key` its sibling money-POSTs require.
- **U14 — Lifecycle: started ≠ drained** (extension of U5). U5 asks *is it wired?*;
  U14 asks *is it stopped correctly?* For every background task the diff adds, the
  composition root's **shutdown path must be read in full — even when that file is not
  in the diff** — and the task checked for join/cancel/bounded-drain against its
  siblings. Caught: a bare `go Reconciler.Run(ctx)` twenty lines from `workerWg`-joined
  siblings.
- **U3 extended — producer-side event IDs.** For any event another service consumes to
  move money, the event ID is the consumer's only dedup key under at-least-once, so it
  must be deterministic (`<event_type>:<aggregate_id>`), never `uuid.New()` per emit.
  New panel question for every cross-service event: *what does the consumer dedup on?*
- **go-postgres — money rounding.** `decimal.Div`/`Mul` results representing money must
  round to the currency's minor unit **at computation**, not at the API boundary, so the
  live value, the persisted row, and every replay agree by construction. Names the trap
  (shopspring `decimal.Div` defaults to `DivisionPrecision = 16`) and the invariant
  (does the client's value equal the persisted one, byte for byte?). Minor-unit exponent
  derives from the currency, never hardcoded.
- Reviewer D is now **CI parity + reachability + lifecycle** and returns `lifecycle_gaps`
  alongside `reachability_gaps` (build-record shape stays backward-compatible).
  Reviewer A owns U13 + U3's cross-service consumer contract; Reviewer B owns the
  money-precision live-vs-persisted check.

Fixed
- **review-memory `recall` relevance.** The filter was `any(token in haystack)` over every
  field, which failed both ways on a real 54-decision corpus: it **flooded** (one common
  token selected everything — `dart` matched 54/54, `lib` 52/54, so `--area` was a no-op)
  and it **silently returned nothing** for path-only areas, because paths were never split
  (`--area "lib/features/meetings/view/meeting_player_page.dart"` → 0 decisions, which
  looks identical to "no memory yet"). Now path-anchored with document-frequency filtering
  (`GENERIC_DF = 0.5`) applied to path segments as well as keywords, so the corpus decides
  what's generic instead of a hardcoded stoplist that rots. Falls back to showing
  everything when nothing discriminating survives; watch items stay on the loose filter.
  Deterministic and dependency-free by design — a fuzzy match here could **suppress** a
  real finding. Adds `tests/test_memory.py`, the first test suite for `memory.py`.

Changed
- **Snapshot honesty.** The reviewed `head_sha`/`base_sha` are recorded in `meta.json`,
  rendered in the HTML report header, and the short head SHA appears in the Slack verdict
  — a verdict without a SHA is unreconcilable once the branch moves. Merge conflicts are
  now **re-verified with `git merge-tree` at delivery time**, not only at fetch; if the
  head moved or the target advanced in between, the verdict says so instead of reporting
  a stale clean. (Real case: clean at 18:09, target advanced 18:28, branch conflicted.)
- Persona prompts now state explicitly that **findings are not limited to changed files**
  — unchanged code whose contract or risk the diff changes is in scope.

## 1.8.1

Fixed
- **Installer no longer creates duplicate skills.** `install.sh` used to back up an
  existing skill in place to `~/.claude/skills/<name>.bak` — but that dir still contains
  a `SKILL.md`, so Claude Code registered it as a *second* skill (e.g. `slack-send` **and**
  `slack-send.bak`). Backups now go to `~/.claude/.pr-review-loop-backups/` (outside the
  skills path), and the installer removes any stale `*.bak` skill dirs left by older
  versions. Fixes the "same skill appears twice" duplication.

## 1.8.0

Stack-aware review engine — biggest change since the panel shipped. Designed from an
audit of 675 real review comments across 16 repos + a 146-repo portfolio scan.

Added
- **New shared `review-core` skill** — the single source of truth for review quality:
  the reviewer personas (A/B/C + Reviewer D), the **universal lenses** (U1–U12,
  stack-agnostic principles), a **resolver** (stack + library detection), and pluggable
  **stack lens packs**. Both `/review-pr` (inline) and `review-pr-slack` now delegate to
  it, so the review brain is defined once, not duplicated.
- **Stack lens packs** (`review-core/references/lenses/`): full packs for `go-postgres`,
  `flutter-bloc`, `flutter-mobx`, `nestjs`; stubs for `react`, `flutter-provider`,
  `flutter-riverpod`, `python`. Composed as **base + overlays** (e.g. `_base-flutter` +
  `flutter-mobx`). Unknown stack → universal-only fallback. Add a stack by dropping a
  file in `lenses/` + a resolver row — no command changes.
- **Reviewer D now runs on the inline `/review-pr` path too** (it was Slack-only) — so
  compile/lint/CI/reachability blockers are caught inline.
- Universal lenses capture the highest-value findings the old Flutter-only prompts
  missed: SQL/TOCTOU races, write+event atomicity, idempotency, fail-closed security,
  **reachability (defined ≠ wired)**, spec/AC match, test-effectiveness, stale-doc.
- **Reporting-completeness rule** (personas + `_base-flutter`): reviewers must still
  enumerate the low-severity design-system / i18n / naming P2 nits (the ones human
  reviewers leave most) even when the MR also has P0/P1s — depth must not crowd out
  breadth. Validated on a real A/B: the new engine found a P0 mock-in-prod, a P1
  double-refund idempotency gap, and an unreachable feature that the old engine and the
  human reviewer both missed; this rule keeps the style sweep from being dropped.

Changed
- **Reviewer D mirrors the repo's REAL CI** instead of a generic build: reads
  `.gitlab-ci.yml`/`.github/workflows` and runs its exact lint/test/build — formatter
  gates (`gofmt -l`, `dart format --set-exit-if-changed`), analyzers, and **build tags**
  (`//go:build e2e`, which `go build ./...` skips). Checks head pipeline status.
- **Merge-conflict check verifies with `git merge-tree`** (universal lens U9) rather than
  trusting the lazily-computed `has_conflicts`/`merge_status` API flag, which can be
  stale. Re-reviews verify "fixed" at HEAD, not from `resolved=true`; stacked-MR aware.
- `/review-pr-doctor` prints which lens pack(s) the current repo resolves to.

## 1.7.1

Added
- Reviewer D (Build & Analyze) now cleans up after itself: after compiling/analyzing
  in its throwaway worktree it runs the stack's clean (`flutter clean` / `dart clean`
  / `go clean`) before removing the worktree, so no build artifacts linger and the
  teardown can't be blocked. Never touches the user's real checkout.

## 1.7.0

Added
- Merge-conflict detection in every reviewer: checks the PR/MR against its target
  (`has_conflicts`/`merge_status` on GitLab, `mergeable`/`mergeStateStatus` on
  GitHub). A conflicting PR is **never approved** — verdict is forced to Request
  Changes with a P1 "resolve conflicts" finding. The HTML report gains a
  **Conflicts column** (⚠ conflicts / ✓ no conflicts) and the Slack reaction goes
  🔧 on conflict.

## 1.6.0

Changed
- Reviewers now **auto-adapt to the repo's stack** instead of assuming Flutter.
  The panel detects the stack from the repo manifest (pubspec / package.json /
  go.mod / pyproject / csproj…) and applies that stack's idioms + the repo's own
  linter/CLAUDE.md. Complexity thresholds prefer the repo's linter config
  (analysis_options / .eslintrc / .golangci / setup.cfg) and fall back to
  per-language defaults; the UI component-nesting rule applies to frontend only
  (backend has no build method).

## 1.5.1

Changed
- Complexity thresholds aligned to Dart Code Metrics defaults (6–8 nesting was too
  strict). UI widget nesting flags at **> 10** (DCM Widgets Nesting Level ≤ 10);
  cyclomatic complexity **> 20** = P1 (DCM default); control-flow nesting **> 5**
  (DCM maximum-nesting-level). Widget depth 6–10 is normal and no longer flagged.

## 1.5.0

Added
- Complexity check in every reviewer: measures method complexity and flags the
  worst. UI build methods with widget/element **nesting > 6–8** are marked as
  oversized (extract sub-widgets); other methods with high **cyclomatic
  complexity** are raised as **P1** ("split into smaller functions"), with the
  measured depth / branch count cited as evidence.

## 1.4.0

Added
- Interactive HTML report (in a browser): per-comment status (fixed / disagree /
  later) + reply box, per-file "viewed" collapse, expand/collapse all, stable
  comment `#id`s, and a **Copy Next Round** button that assembles all responses
  into Slack text. State persists in localStorage. The copied text pastes into the
  PR thread and feeds the next round (status tags map to memory resolutions).

## 1.3.2

Changed
- Slack auth failures now **prompt** instead of dead-ending. On a missing token or
  scope, an interactive run asks (AskUserQuestion) whether to reconnect Slack and
  runs the re-auth for you; a `/loop` run reports once and stops instead of
  erroring every cycle. `watch.sh` emits `SCOPE_ERROR` (exit 4) so the skill can
  branch on it.

## 1.3.1

Added
- Documented terminal install via the `claude plugin` CLI (`claude plugin
  marketplace add` / `claude plugin install`) — same result as the `/plugin`
  slash commands, runnable from a shell.

Fixed
- SessionStart hook now also best-effort installs `shiki`, so a marketplace / CLI
  install is fully self-sufficient (HTML report highlighting works without running
  install.sh).

## 1.3.0

Added
- One-line global install: `curl -fsSL .../install-remote.sh | bash` clones the
  plugin to ~/.pr-review-loop and installs into ~/.claude for the user (all
  projects). Re-run to update.

## 1.2.1

Fixed
- slack-send OAuth now requests the read scopes the watcher and reactions need:
  `channels:history`, `groups:history`, `im:history`, `mpim:history`,
  `reactions:read`, `reactions:write`. Existing installs must re-run
  `~/.claude/skills/slack-send/install.sh` (re-auth) to grant them.

## 1.2.0

Added
- `/review-pr-init` — guided first-time setup. Asks which PR platform you use
  (required) and whether you want Slack delivery and graphify (optional), then
  connects them and runs the doctor. No more hand-running installers.

## 1.1.0

Added
- `/review-pr-doctor` — setup self-check (auth, skills, Slack token, graphify, shiki)
  with fix-it guidance.
- Per-repo config: `.review-memory/config.json` (cycle cap, watch channel, state
  emojis, stack, extra generated globs). `memory.py config . --init` writes a
  default; watchers read it.
- `--dry-run` for both watchers — report what would be reviewed without acting.
- `memory.py health` — review-health report: volume, dispute rate per category
  (precision proxy), open watch items, deferred-not-closed.

Notes
- The PR watcher intentionally **skips a bare re-request with no new commits** —
  the head is unchanged, so there is nothing new to review.
- Hooks and scripts are bash; on native Windows use WSL.

## 1.0.0

- `/review-pr` panel review (inline) with per-repo self-improving review memory.
- `/review-pr-slack` — panel → HTML report + Slack verdict; reads a Slack thread to
  find PR links and replies the verdict there.
- `/review-pr-watch` and `/review-pr-slack-watch` — loop drivers (reactions and
  PR+commit dedup as state).
- Review memory: recall / record / sticky human watch items / distill / ripe;
  never overrides CLAUDE.md / ADRs; human promotes recurring lessons.
- Best-effort graphify auto-install; shiki-baked report highlighting.
