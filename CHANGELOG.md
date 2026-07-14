# Changelog

All notable changes to pr-review-loop. Teammates: after a maintainer pushes, run
`/plugin marketplace update pr-review-loop` then reinstall to get the latest.

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
