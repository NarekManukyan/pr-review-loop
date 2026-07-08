#!/usr/bin/env bash
# SessionStart hook for the pr-review-loop plugin.
#   1. Ensures the review-memory skill is available at ~/.claude/skills/ so the
#      /review-pr command's memory.py path resolves (marketplace installs bundle
#      the skill inside the plugin; the command uses the standard skills path).
#   2. If the current repo has a .review-memory/ corpus, surfaces findings that
#      have recurred enough with a consistent developer verdict — a nudge to
#      promote them into CLAUDE.md/an ADR. Human decides; nothing auto-edits.
# Always exits 0 so it can never block a session.
set -u

DEST="$HOME/.claude/skills/review-memory"
SRC="${CLAUDE_PLUGIN_ROOT:-}/skills/review-memory"

# 1. ensure-install (copy if missing or older) — idempotent, best-effort
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "$SRC" ]; then
  if [ ! -f "$DEST/scripts/memory.py" ]; then
    mkdir -p "$HOME/.claude/skills"
    cp -R "$SRC" "$DEST" 2>/dev/null || true
  elif [ "$SRC/scripts/memory.py" -nt "$DEST/scripts/memory.py" ]; then
    cp -R "$SRC/." "$DEST/" 2>/dev/null || true
  fi
fi

MEM="$DEST/scripts/memory.py"
[ -f "$MEM" ] || exit 0
command -v python3 >/dev/null 2>&1 || exit 0

# One-time best-effort graphify install, backgrounded so it NEVER blocks session
# start. Marker inside the script prevents repeat attempts. Optional — JSONL
# recall works without it.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-graphify.sh" ] \
   && [ ! -f "$HOME/.claude/.pr-review-loop-graphify-checked" ] && ! command -v graphify >/dev/null 2>&1; then
  nohup bash "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-graphify.sh" >/dev/null 2>&1 &
fi

# 2. nudge only when this repo has review memory with ripe candidates
[ -d "./.review-memory" ] || exit 0
RIPE="$(python3 "$MEM" ripe . 2>/dev/null)"
[ -z "$RIPE" ] && exit 0

COUNT="$(printf '%s\n' "$RIPE" | grep -c .)"
echo "🧠 Review memory: ${COUNT} recurring finding(s) have a consistent developer verdict and are ripe to codify into CLAUDE.md / an ADR:"
printf '%s\n' "$RIPE" | head -5 | sed 's/^/   • /'
echo "   Review with: python3 ~/.claude/skills/review-memory/scripts/memory.py distill .  (human promotes; nothing auto-edits)"
exit 0
