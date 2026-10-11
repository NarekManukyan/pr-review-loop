#!/usr/bin/env bash
# Standalone installer for the pr-review-loop plugin (no marketplace needed).
# Installs the commands + bundled skills into ~/.claude. The one-click path is the
# Claude Code marketplace (see README); this is the zip/clone fallback.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.claude/commands" "$HOME/.claude/skills"

echo "Installing commands -> ~/.claude/commands/"
cp "$SRC"/commands/*.md "$HOME/.claude/commands/"

# Reviewer agent definitions. These carry a MINIMAL toolset on purpose: a
# general-purpose agent re-sends ~100 unused MCP tool schemas every turn
# (measured ~5.4k tok/turn — the largest single cost in a review round).
echo "Installing reviewer agents -> ~/.claude/agents/"
mkdir -p "$HOME/.claude/agents"
cp "$SRC"/agents/*.md "$HOME/.claude/agents/"

# CLI wrapper. Claude Code puts a plugin's bin/ on PATH automatically, but that
# only applies INSIDE Claude Code — a real terminal never sees it. ~/.local/bin is
# the conventional user bin dir and is already on most PATHs, so link it there too
# and say so if it is not on PATH.
echo "Installing CLI -> ~/.local/bin/review-stats"
mkdir -p "$HOME/.local/bin"
ln -sf "$SRC/bin/review-stats" "$HOME/.local/bin/review-stats"
chmod +x "$SRC/bin/review-stats" 2>/dev/null || true
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) echo "  note: ~/.local/bin is not on your PATH — add this to your shell profile:"
     echo '        export PATH="$HOME/.local/bin:$PATH"' ;;
esac

PLUGIN_VERSION="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
                  "$SRC/.claude-plugin/plugin.json" 2>/dev/null | head -1)"
[ -z "$PLUGIN_VERSION" ] && PLUGIN_VERSION="unknown"
echo "Installing bundled skills -> ~/.claude/skills/ (v$PLUGIN_VERSION)"
# Back up any existing copy OUTSIDE ~/.claude/skills — an in-place "<name>.bak" dir
# still contains a SKILL.md, so Claude Code would register it as a duplicate skill.
BACKUP_DIR="$HOME/.claude/.pr-review-loop-backups"
for s in "$SRC"/payload/skills/*/; do
  name="$(basename "$s")"
  if [ -d "$HOME/.claude/skills/$name" ]; then
    mkdir -p "$BACKUP_DIR"
    rm -rf "$BACKUP_DIR/$name"
    mv "$HOME/.claude/skills/$name" "$BACKUP_DIR/$name"
  fi
  cp -R "$s" "$HOME/.claude/skills/$name"
  # Stamp which plugin version produced this copy, so the SessionStart hook can
  # tell "up to date" from "stale engine" and /review-pr-doctor can report it.
  printf '%s\n' "$PLUGIN_VERSION" > "$HOME/.claude/skills/$name/.installed-version" 2>/dev/null || true
  echo "  - $name ($PLUGIN_VERSION)"
done
# One-time cleanup: remove stale in-place *.bak skill dirs left by older installers
# (they registered as duplicate skills). The real skills were just (re)installed above.
for b in "$HOME"/.claude/skills/*.bak; do
  [ -d "$b" ] && [ -f "$b/SKILL.md" ] && rm -rf "$b"
done

# Retired in this release: the Slack front-end. Remove what earlier installs left.
rm -f "$HOME/.claude/commands/review-pr-slack-watch.md"
if [ -d "$HOME/.claude/skills/review-pr-slack" ]; then
  mkdir -p "$BACKUP_DIR"
  rm -rf "$BACKUP_DIR/review-pr-slack"
  mv "$HOME/.claude/skills/review-pr-slack" "$BACKUP_DIR/review-pr-slack"
  echo "  - review-pr-slack retired (moved to $BACKUP_DIR)"
fi

echo "Ensuring graphify (optional semantic recall)…"
bash "$SRC/scripts/ensure-graphify.sh" --force || true

echo
echo "Done. Restart Claude Code (new session), then run /review-pr-init for guided setup."
echo
echo "Commands:"
echo "  /review-pr <PR_URL>                     panel review + review memory (inline, this repo)"
echo "  /review-pr-watch [owner/repo]           one watch cycle for re-review requests (wrap in /loop)"
echo "  /review-pr-init                         guided setup (PR platform required; graphify optional)"
echo "  /review-pr-doctor                       check setup (auth, skills, graphify)"
echo "  /review-pr-stats                        real token usage + review activity (from logs)"
echo
echo "CLI (any terminal, no Claude Code needed):"
echo "  review-stats                            same stats for the repo you are in"
echo "  review-stats --json                     machine-readable"
echo
echo "Prerequisites:"
echo "  - gh CLI authenticated (or glab for GitLab)"
echo "  - graphify: auto-installed above if possible; JSONL recall works even without it"
echo
echo "Review memory learns per repo from developer responses; recurring lessons get promoted"
echo "by a human into CLAUDE.md/an ADR (run: memory.py distill .). Memory never overrides CLAUDE.md."
