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

echo "Installing bundled skills -> ~/.claude/skills/"
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
  echo "  - $name"
done
# One-time cleanup: remove stale in-place *.bak skill dirs left by older installers
# (they registered as duplicate skills). The real skills were just (re)installed above.
for b in "$HOME"/.claude/skills/*.bak; do
  [ -d "$b" ] && [ -f "$b/SKILL.md" ] && rm -rf "$b"
done

# syntax highlighting for the HTML report (review-pr-slack)
if command -v npm >/dev/null 2>&1; then
  echo "Installing shiki (HTML report highlighting)…"
  (cd "$HOME/.claude/skills/review-pr-slack/scripts" && npm install --no-fund --no-audit --silent) || \
    echo "  (shiki install skipped — report falls back to CDN highlighting)"
fi

echo "Ensuring graphify (optional semantic recall)…"
bash "$SRC/scripts/ensure-graphify.sh" --force || true

echo
echo "Done. Restart Claude Code (new session), then run /review-pr-init for guided setup."
echo
echo "Commands:"
echo "  /review-pr <PR_URL>                     panel review + review memory (inline, this repo)"
echo "  /review-pr-watch [owner/repo]           one watch cycle for re-review requests (wrap in /loop)"
echo "  /review-pr-slack <PR_URLs | slack-msg>  panel review -> HTML report + Slack verdict"
echo "  /review-pr-slack-watch #channel         one watch cycle (wrap in /loop to run continuously)"
echo "  /review-pr-init                         guided setup (PR platform required; Slack/graphify optional)"
echo "  /review-pr-doctor                       check setup (auth, skills, token, graphify, shiki)"
echo "  /review-pr-stats                        real token usage + review activity (from logs)"
echo
echo "CLI (any terminal, no Claude Code needed):"
echo "  review-stats                            same stats for the repo you are in"
echo "  review-stats --json                     machine-readable"
echo
echo "Prerequisites:"
echo "  - gh CLI authenticated (or glab for GitLab)"
echo "  - Slack: connect the sender token once ->  ~/.claude/skills/slack-send/install.sh"
echo "    (needed for the Slack verdict message, report upload, and reaction state)"
echo "  - graphify: auto-installed above if possible; JSONL recall works even without it"
echo
echo "Reactions encode PR state on the trigger message: 👀 reviewing · ✅ approved · 🔧 changes requested."
echo "Review memory learns per repo from developer responses; recurring lessons get promoted"
echo "by a human into CLAUDE.md/an ADR (run: memory.py distill .). Memory never overrides CLAUDE.md."
