#!/usr/bin/env bash
# Installs the review-pr-slack skill into ~/.claude/skills for the current user.
set -euo pipefail

DEST="$HOME/.claude/skills/review-pr-slack"
SRC="$(cd "$(dirname "$0")" && pwd)"

echo "Installing review-pr-slack skill -> $DEST"
mkdir -p "$DEST"
cp -R "$SRC/SKILL.md" "$SRC/references" "$SRC/scripts" "$DEST/"

if command -v node >/dev/null 2>&1 && command -v npm >/dev/null 2>&1; then
  echo "Installing shiki (syntax highlighting) ..."
  (cd "$DEST/scripts" && npm install --no-fund --no-audit --silent)
else
  echo "WARNING: node/npm not found — reports will fall back to CDN-based"
  echo "highlighting (works in browsers, not in Slack previews)."
fi

echo
echo "Done. Restart Claude Code (or start a new session) and use it with:"
echo "  /review-pr-slack <MR/PR URLs...>"
echo
echo "Prerequisites:"
echo "  - glab CLI authenticated (GitLab) or gh CLI (GitHub)"
echo "  - Slack connector enabled in Claude Code (claude.ai connectors)"
