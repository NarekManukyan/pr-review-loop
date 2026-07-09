# Changelog

All notable changes to pr-review-loop. Teammates: after a maintainer pushes, run
`/plugin marketplace update pr-review-loop` then reinstall to get the latest.

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
