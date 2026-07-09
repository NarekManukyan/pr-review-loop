#!/usr/bin/env bash
# Standalone installer for the pr-review-loop plugin (no marketplace needed).
# Installs the commands + bundled skills into ~/.claude. The one-click path is the
# Claude Code marketplace (see README); this is the zip/clone fallback.
set -euo pipefail

SRC="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$HOME/.claude/commands" "$HOME/.claude/skills"

echo "Installing commands -> ~/.claude/commands/"
cp "$SRC"/commands/*.md "$HOME/.claude/commands/"

echo "Installing bundled skills -> ~/.claude/skills/"
for s in "$SRC"/payload/skills/*/; do
  name="$(basename "$s")"
  rm -rf "$HOME/.claude/skills/$name.bak"
  [ -d "$HOME/.claude/skills/$name" ] && mv "$HOME/.claude/skills/$name" "$HOME/.claude/skills/$name.bak"
  cp -R "$s" "$HOME/.claude/skills/$name"
  echo "  - $name"
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
