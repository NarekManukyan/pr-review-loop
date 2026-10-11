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
STAMP=".installed-version"   # per-skill marker: which plugin version installed this copy

# 1. sync bundled skills into ~/.claude/skills — idempotent.
#
# This used to gate on SKILL.md's mtime alone, which was wrong: git only rewrites
# files a commit actually changed, so a release touching only references/ left
# SKILL.md's mtime untouched and the sync never fired. The install kept a stale
# engine while reporting the new plugin version — and references/ is where most
# of this plugin's releases land (personas, lenses, stack packs).
#
# Gate on the plugin version instead, and keep an mtime sweep of the whole tree so
# local iteration on payload/ still propagates without a version bump.
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -d "$PAYLOAD" ]; then
  mkdir -p "$SKILLS_DEST"
  PLUGIN_VERSION="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
                    "${CLAUDE_PLUGIN_ROOT}/.claude-plugin/plugin.json" 2>/dev/null | head -1)"
  [ -z "$PLUGIN_VERSION" ] && PLUGIN_VERSION="unknown"
  for s in "$PAYLOAD"/*/; do
    [ -d "$s" ] || continue
    dst="$SKILLS_DEST/$(basename "$s")"
    need=0
    if [ ! -e "$dst" ] || [ ! -f "$dst/$STAMP" ]; then
      need=1                                              # never installed, or pre-stamp install
    elif [ "$(cat "$dst/$STAMP" 2>/dev/null)" != "$PLUGIN_VERSION" ]; then
      need=1                                              # plugin moved: ship the new engine
    elif [ -n "$(find "$s" -newer "$dst/$STAMP" -print -quit 2>/dev/null)" ]; then
      need=1                                              # payload edited since last sync
    fi
    if [ "$need" -eq 1 ]; then
      cp -R "$s" "$dst" 2>/dev/null || true
      printf '%s\n' "$PLUGIN_VERSION" > "$dst/$STAMP" 2>/dev/null || true
    fi
  done
fi

MEM="$SKILLS_DEST/review-memory/scripts/memory.py"

# 2. one-time best-effort graphify install, backgrounded so it NEVER blocks start
if [ -n "${CLAUDE_PLUGIN_ROOT:-}" ] && [ -x "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-graphify.sh" ] \
   && [ ! -f "$HOME/.claude/.pr-review-loop-graphify-checked" ] && ! command -v graphify >/dev/null 2>&1; then
  nohup bash "${CLAUDE_PLUGIN_ROOT}/scripts/ensure-graphify.sh" >/dev/null 2>&1 &
fi

# 2b. retire skills this plugin used to ship. Only a copy carrying our install stamp
# is removed — a hand-installed copy is the user's, and the doctor reports it instead.
for retired in review-pr-slack; do
  [ -f "$SKILLS_DEST/$retired/$STAMP" ] && rm -rf "${SKILLS_DEST:?}/$retired"
done

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
