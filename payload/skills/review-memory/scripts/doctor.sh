#!/usr/bin/env bash
# pr-review-loop setup self-check. Verifies everything the plugin needs and prints
# PASS / WARN / FAIL per item. Never fatal — informational only.
# Run via /review-pr-doctor, or directly: bash scripts/doctor.sh
set -u

pass() { printf "  \033[32mPASS\033[0m  %s\n" "$1"; }
warn() { printf "  \033[33mWARN\033[0m  %s\n" "$1"; }
fail() { printf "  \033[31mFAIL\033[0m  %s\n" "$1"; }
have() { command -v "$1" >/dev/null 2>&1; }

echo "pr-review-loop doctor"
echo

echo "core:"
have python3 && pass "python3 $(python3 -V 2>&1 | awk '{print $2}')" || fail "python3 not found (required)"
if have gh; then
  if gh auth status >/dev/null 2>&1; then pass "gh authenticated ($(gh api user --jq .login 2>/dev/null))"; else warn "gh present but not authenticated (run: gh auth login)"; fi
elif have glab; then
  if glab auth status >/dev/null 2>&1; then pass "glab authenticated"; else warn "glab present but not authenticated (run: glab auth login)"; fi
else
  fail "neither gh (GitHub) nor glab (GitLab) found — needed to fetch PRs"
fi

echo
echo "skills (~/.claude/skills):"
for s in review-core review-memory review-pr-slack slack-send; do
  if [ -d "$HOME/.claude/skills/$s" ]; then pass "$s installed"; else warn "$s missing (re-run install.sh, or restart to let the SessionStart hook sync it)"; fi
done
MEM="$HOME/.claude/skills/review-memory/scripts/memory.py"
if [ -f "$MEM" ] && python3 "$MEM" stats . >/dev/null 2>&1; then pass "memory.py runnable"; else warn "memory.py not runnable yet"; fi

echo
echo "commands (~/.claude/commands):"
for c in review-pr review-pr-watch review-pr-slack-watch review-pr-stats; do
  [ -f "$HOME/.claude/commands/$c.md" ] && pass "/$c" || warn "/$c not in ~/.claude/commands (marketplace installs discover it from the plugin instead)"
done

echo
echo "slack (only needed for /review-pr-slack + the Slack watcher):"
if [ -n "${SLACK_UPLOAD_TOKEN:-}" ] || [ -f "$HOME/.slack-upload-token" ]; then
  pass "sender token present"
else
  warn "no Slack token — run ~/.claude/skills/slack-send/install.sh (skip if you only use /review-pr)"
fi

echo
echo "optional:"
if have node && have npm; then
  if [ -d "$HOME/.claude/skills/review-pr-slack/scripts/node_modules/shiki" ]; then pass "shiki installed (HTML report highlighting baked in)"; else warn "shiki not installed — report falls back to CDN highlighting (not visible in Slack preview). Fix: (cd ~/.claude/skills/review-pr-slack/scripts && npm install)"; fi
else
  warn "node/npm not found — HTML report uses CDN highlighting (browser-only)"
fi
if have graphify; then pass "graphify present (semantic review-memory recall)"; else warn "graphify not installed — deterministic JSONL recall still works. Add later: pipx install graphifyy"; fi

echo
echo "this repo:"
if [ -d "./.review-memory" ]; then
  pass ".review-memory/ present ($(python3 "$MEM" stats . 2>/dev/null | head -1))"
else
  warn "no .review-memory/ yet — created on first review, or run: python3 $MEM config . --init"
fi
# stack resolver preview — which lens pack(s) the review engine would load here
detect_stack() {
  local base="" packs=""
  if [ -f pubspec.yaml ]; then
    base="Flutter"; packs="_base-flutter"
    grep -qE '^\s*(flutter_bloc|bloc):' pubspec.yaml 2>/dev/null && packs="$packs + flutter-bloc"
    grep -qE '^\s*(mobx|flutter_mobx):' pubspec.yaml 2>/dev/null && packs="$packs + flutter-mobx"
    grep -qE '^\s*(riverpod|flutter_riverpod|hooks_riverpod):' pubspec.yaml 2>/dev/null && packs="$packs + flutter-riverpod"
    grep -qE '^\s*provider:' pubspec.yaml 2>/dev/null && packs="$packs + flutter-provider"
  elif [ -f go.mod ]; then base="Go"; packs="go-postgres"
  elif [ -f package.json ]; then
    base="JS/TS"
    if grep -q '"@nestjs/core"' package.json 2>/dev/null; then packs="nestjs"
    elif grep -qE '"(next|react)"' package.json 2>/dev/null; then packs="react (stub)"
    else packs="universal-only"; fi
  elif [ -f pyproject.toml ] || [ -f requirements.txt ] || [ -f setup.cfg ]; then base="Python"; packs="python (stub)"
  fi
  if [ -n "$base" ]; then pass "review engine would load: $base → $packs"; else warn "no known manifest here — review engine falls back to universal-only"; fi
}
detect_stack

echo
echo "Legend: PASS = ready · WARN = optional/only needed for some features · FAIL = fix before use."
