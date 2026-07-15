# Changelog

All notable changes to pr-review-loop. Teammates: after a maintainer pushes, run
`/plugin marketplace update pr-review-loop` then reinstall to get the latest.

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
