#!/usr/bin/env bash
# Standalone installer for the mone-review plugin (no marketplace needed).
# Installs the /review-pr command and the review-memory skill into ~/.claude.
# The one-click path is the Claude Code marketplace (see README); this script is
# the zip/clone fallback for machines that can't add a marketplace.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"

mkdir -p "$HOME/.claude/commands" "$HOME/.claude/skills"
echo "Installing /review-pr command -> ~/.claude/commands/review-pr.md"
cp "$SRC/commands/review-pr.md" "$HOME/.claude/commands/review-pr.md"

echo "Installing review-memory skill -> ~/.claude/skills/review-memory"
rm -rf "$HOME/.claude/skills/review-memory.bak"
[ -d "$HOME/.claude/skills/review-memory" ] && mv "$HOME/.claude/skills/review-memory" "$HOME/.claude/skills/review-memory.bak"
cp -R "$SRC/skills/review-memory" "$HOME/.claude/skills/review-memory"

echo
echo "Done. Restart Claude Code (new session), then run /review-pr <PR_URL>."
echo
echo "Prerequisites:"
echo "  - gh CLI authenticated (or glab for GitLab)"
echo "  - graphify (optional) for semantic review-memory recall; plain JSONL recall works without it"
echo
echo "Auto-improvement: after each review the panel records findings + how you"
echo "responded into a committed .review-memory/ folder in the repo, and recalls"
echo "them next time. When a finding keeps getting the same verdict, you'll be"
echo "nudged to codify it into CLAUDE.md / an ADR. Memory never overrides CLAUDE.md."
echo
echo "(The SessionStart nudge only runs when installed as a plugin via the"
echo "marketplace. With this standalone install, run distill yourself:"
echo "  python3 ~/.claude/skills/review-memory/scripts/memory.py distill .)"
