#!/usr/bin/env bash
# install.sh — one-time setup for the slack-send skill (messages + file uploads).
# 1) copies the skill into ~/.claude/skills/ and the /slack-send command into ~/.claude/commands/
# 2) connects your personal Slack token via a browser OAuth flow (posts as YOU).
#
# Usage:
#   ./install.sh                 # installs, then opens the browser to connect Slack
#   ./install.sh xoxp-...        # skip OAuth, use this token directly
#   SLACK_TOKEN=xoxp-... ./install.sh
#   ./install.sh --manual        # skip OAuth, paste a token yourself
#   ./install.sh --no-token      # only install files, connect later
#   ./install.sh --desktop       # force-register the MCP server in Claude Desktop
#   ./install.sh --no-desktop    # skip Claude Desktop registration
#   (By default it AUTO-registers for Claude Desktop when Desktop is detected on this Mac,
#    so a from-scratch install sets up BOTH Claude Code and Claude Desktop chat.)
#
# The browser flow needs nothing from you but a click on "Allow" — no admin page,
# no copy-paste. (Advanced: override CC_CLIENT_ID / CC_CLIENT_SECRET / CC_PORT.)
set -euo pipefail

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$HOME/.claude/skills"
DEST_DIR="$SKILLS_ROOT/slack-send"
CMD_DIR="$HOME/.claude/commands"
TOKEN_FILE="$HOME/.slack-upload-token"
OWNER_FILE="$HOME/.slack-upload-owner"

# CC File Sender app (m-oneteam). Public client_id + secret for THIS internal app;
# override via env if the app is rotated.
export CC_CLIENT_ID="${CC_CLIENT_ID:-1791240383761.11560951127808}"
export CC_CLIENT_SECRET="${CC_CLIENT_SECRET:-d737e112d4079bd11d0030a39e68daaa}"
export CC_PORT="${CC_PORT:-53682}"

# --- parse desktop flags out of the args (rest flow to token handling) ---
# Default: auto-register the MCP server if Claude Desktop is detected on this machine.
#   --desktop     force registration even if not auto-detected
#   --no-desktop  skip registration entirely
DESKTOP=""
NO_DESKTOP=""
ARGS=()
for a in "$@"; do
  case "$a" in
    --desktop) DESKTOP=1 ;;
    --no-desktop) NO_DESKTOP=1 ;;
    *) ARGS+=("$a") ;;
  esac
done
set -- ${ARGS[@]+"${ARGS[@]}"}

# auto-detect Claude Desktop (macOS) unless explicitly opted out
if [ -z "$NO_DESKTOP" ] && [ -d "$HOME/Library/Application Support/Claude" ]; then
  DESKTOP=1
fi

register_desktop() {
  local cfg_dir="$HOME/Library/Application Support/Claude"
  local cfg="$cfg_dir/claude_desktop_config.json"
  local server="$DEST_DIR/scripts/mcp_server.py"
  mkdir -p "$cfg_dir"
  [ -f "$cfg" ] && cp "$cfg" "$cfg.bak.$(date +%s)"
  SSERVER="$server" python3 - "$cfg" <<'PY'
import json, os, sys
cfg = sys.argv[1]; server = os.environ["SSERVER"]
data = {}
if os.path.exists(cfg):
    try: data = json.load(open(cfg))
    except Exception: data = {}
data.setdefault("mcpServers", {})["slack-send"] = {"command": "python3", "args": [server]}
json.dump(data, open(cfg, "w"), indent=2)
print("registered 'slack-send' in", cfg)
PY
  say "Registered MCP server in Claude Desktop → restart Claude Desktop to load it."
}

say() { printf '%s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# --- 0. sanity ---
[ -f "$SRC_DIR/scripts/send.sh" ] && [ -f "$SRC_DIR/scripts/msg.sh" ] \
  || die "scripts not found next to install.sh — run this from inside the slack-send folder."

# --- 1. install skill files ---
if [ "$SRC_DIR" != "$DEST_DIR" ]; then
  say "Installing skill -> $DEST_DIR"
  mkdir -p "$DEST_DIR"
  if command -v rsync >/dev/null 2>&1; then
    rsync -a --exclude '.git' --exclude 'node_modules' "$SRC_DIR"/ "$DEST_DIR"/
  else
    (cd "$SRC_DIR" && tar --exclude='.git' --exclude='node_modules' -cf - .) | (cd "$DEST_DIR" && tar -xf -)
  fi
else
  say "Skill already in place: $DEST_DIR"
fi
chmod +x "$DEST_DIR"/scripts/*.sh "$DEST_DIR/install.sh" 2>/dev/null || true

# --- 2. install slash command ---
if [ -f "$DEST_DIR/command/slack-send.md" ]; then
  mkdir -p "$CMD_DIR"
  cp "$DEST_DIR/command/slack-send.md" "$CMD_DIR/slack-send.md"
  say "Installed slash command -> $CMD_DIR/slack-send.md"
fi

# --- 2c. register MCP server in Claude Desktop (only with --desktop) ---
[ -n "$DESKTOP" ] && register_desktop

# --- 3. token setup (unless --no-token) ---
if [ "${1:-}" = "--no-token" ]; then
  say ""; say "✅ Files installed. Skipped token setup (--no-token)."
  say "   Run  $DEST_DIR/install.sh  again with your xoxp- token to finish."
  exit 0
fi

ARG="${1:-}"
MANUAL=""
[ "$ARG" = "--manual" ] && { MANUAL=1; ARG=""; }
TOKEN="${ARG:-${SLACK_TOKEN:-}}"

if [ -z "$TOKEN" ] && [ -z "$MANUAL" ]; then
  # --- browser OAuth (default): captures a personal user token, no admin page ---
  say "Connecting your Slack (a browser window will open — just click Allow)..."
  # oauth.py captures the authorization code; we exchange it with curl (system SSL).
  if OUT="$(python3 "$DEST_DIR/scripts/oauth.py")"; then RC=0; else RC=$?; fi
  case "$OUT" in
    ERR:*) die "Slack OAuth error: ${OUT#ERR: }" ;;
  esac
  { [ "$RC" -eq 0 ] && [ -n "$OUT" ]; } || die "OAuth failed (no code returned). Retry: bash install.sh"
  CODE="$OUT"
  EX="$(curl -s -X POST https://slack.com/api/oauth.v2.access \
        --data-urlencode "client_id=$CC_CLIENT_ID" \
        --data-urlencode "client_secret=$CC_CLIENT_SECRET" \
        --data-urlencode "code=$CODE" \
        --data-urlencode "redirect_uri=http://localhost:${CC_PORT}/callback" \
        --data-urlencode "grant_type=authorization_code")"
  printf '%s' "$EX" | grep -q '"ok":true' || die "token exchange rejected: $EX"
  TOKEN="$(printf '%s' "$EX" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("authed_user",{}).get("access_token",""))')"
  [ -n "$TOKEN" ] || die "no user token in exchange response: $EX"
fi

if [ -z "$TOKEN" ]; then
  # --manual fallback
  say "Paste your Slack User OAuth Token (xoxp-...) and press Enter:"
  read -r -s TOKEN
  echo
fi
[ -n "$TOKEN" ] || die "no token obtained"
case "$TOKEN" in
  xoxp-*) : ;;
  xoxb-*) say "WARNING: that's a BOT token (xoxb-). Posts will show as the bot, not you. Prefer the User token (xoxp-)." ;;
  *)      die "token doesn't look like a Slack token (expected xoxp-... or xoxb-...)" ;;
esac

say "Validating token..."
RESP="$(curl -s -X POST https://slack.com/api/auth.test -H "Authorization: Bearer $TOKEN")"
OK="$(printf '%s' "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("ok"))' 2>/dev/null || echo False)"
[ "$OK" = "True" ] || die "token rejected by Slack: $RESP"
USER_NAME="$(printf '%s' "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("user",""))')"
USER_ID="$(printf '%s' "$RESP"  | python3 -c 'import sys,json;print(json.load(sys.stdin).get("user_id",""))')"
TEAM="$(printf '%s' "$RESP"     | python3 -c 'import sys,json;print(json.load(sys.stdin).get("team",""))')"
[ -n "$USER_ID" ] || die "could not read user_id from Slack response"

umask 077
printf '%s\n' "$TOKEN"   > "$TOKEN_FILE"; chmod 600 "$TOKEN_FILE"
printf '%s\n' "$USER_ID" > "$OWNER_FILE"; chmod 600 "$OWNER_FILE"

say ""
say "✅ Connected as: $USER_NAME ($USER_ID) on team: $TEAM"
say "   token -> $TOKEN_FILE"
say "   owner -> $OWNER_FILE"
say ""
say "Try it:"
say "   $DEST_DIR/scripts/msg.sh  me \"hello from install\""
say "   $DEST_DIR/scripts/send.sh ~/Desktop/somefile.pdf me"
say "Or in Claude Code:  /slack-send me hello"
say "Done."
