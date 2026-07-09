#!/usr/bin/env bash
# SessionStart hook for the pr-review-loop plugin.
#   1. Syncs the plugin's bundled skills (payload/skills/*) into ~/.claude/skills
#      so the commands' absolute skill paths resolve and each skill is discovered
#      from ONE canonical location (no duplicate registration with the plugin).
#   2. One-time best-effort graphify install, backgrounded (never blocks).
#   3. If the current repo has a .review-memory/ corpus with findings that keep
#      getting the same developer verdict, nudges to codify them into CLAUDE.md/
#      an ADR. Human decides; nothing auto-edits.
# Always exits 0 so it can never block a session.
set -u

SKILLS_DEST="$HOME/.claude/skills"
PAYLOAD="${CLAUDE_PLUGIN_ROOT:-}/payload/skills"

# 1. sync bundled skills (copy when missing or plugin copy is newer) — idempotent
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "$PAYLOAD" ]; then
  mkdir -p "$SKILLS_DEST"
  for s in "$PAYLOAD"/*/; do
    [ -d "$s" ] || continue
    dst="$SKILLS_DEST/$(basename "$s")"
    if [ ! -e "$dst" ] || [ "$s/SKILL.md" -nt "$dst/SKILL.md" ]; then
      cp -R "$s" "$dst" 2>/dev/null || true
    fi
  done
fi

MEM="$SKILLS_DEST/review-memory/scripts/memory.py"

# 2. one-time best-effort graphify install, backgrounded so it NEVER blocks start
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-graphify.sh" ] \
   && [ ! -f "$HOME/.claude/.pr-review-loop-graphify-checked" ] && ! command -v graphify >/dev/null 2>&1; then
  nohup bash "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-graphify.sh" >/dev/null 2>&1 &
fi

# 3. nudge only when this repo has review memory with ripe candidates
[ -f "$MEM" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0
[ -d "./.review-memory" ] || exit 0
RIPE="$(python3 "$MEM" ripe . 2>/dev/null)"
[ -z "$RIPE" ] && exit 0

COUNT="$(printf '%s\n' "$RIPE" | grep -c .)"
echo "🧠 Review memory: ${COUNT} recurring finding(s) have a consistent developer verdict and are ripe to codify into CLAUDE.md / an ADR:"
printf '%s\n' "$RIPE" | head -5 | sed 's/^/   • /'
echo "   Review with: python3 ~/.claude/skills/review-memory/scripts/memory.py distill .  (human promotes; nothing auto-edits)"
exit 0
