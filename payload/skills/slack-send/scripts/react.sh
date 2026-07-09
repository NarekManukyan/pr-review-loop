#!/usr/bin/env bash
# Manage Slack reactions on a message, as the token owner (the reviewer).
# Used by review-pr-slack to encode PR review state on the trigger message:
#   👀 eyes = review in progress · ✅ white_check_mark = approved ·
#   🔧 wrench = changes requested · 🚨 rotating_light = P0/blocker present
#
# Usage:
#   react.sh add    <channel> <ts> <emoji>
#   react.sh remove <channel> <ts> <emoji>
#   react.sh get    <channel> <ts>              # prints reaction names, one per line
#   react.sh state  <channel> <ts> <emoji>      # clear known state emojis, then add <emoji>
#
# <emoji> is a Slack short name WITHOUT colons (eyes, white_check_mark, wrench, rotating_light).
# Token: $SLACK_UPLOAD_TOKEN or ~/.slack-upload-token. Exit: 0 ok | 2 usage | 3 no token.
set -euo pipefail

CMD="${1:?usage: react.sh add|remove|get|state <channel> <ts> [emoji]}"
CH="${2:?channel required}"
TS="${3:?message ts required}"
EMOJI="${4:-}"

# state emojis this tool manages (so `state` can clear stale ones)
STATE_EMOJIS="eyes white_check_mark wrench rotating_light"

TOKEN="${SLACK_UPLOAD_TOKEN:-}"
[ -z "$TOKEN" ] && [ -f "$HOME/.slack-upload-token" ] && TOKEN="$(cat "$HOME/.slack-upload-token")"
if [ -z "$TOKEN" ]; then
  echo "NO_TOKEN: no CC App token (\$SLACK_UPLOAD_TOKEN or ~/.slack-upload-token). Run slack-send/install.sh." >&2
  exit 3
fi

api() { local m="$1"; shift; curl -s -X POST "https://slack.com/api/$m" -H "Authorization: Bearer $TOKEN" "$@"; }

ok() { python3 -c 'import sys,json; d=json.load(sys.stdin); print("1" if d.get("ok") else "0:"+d.get("error",""))'; }

do_add() {
  local r; r="$(api reactions.add -d "channel=$CH" -d "timestamp=$TS" -d "name=$1")"
  local s; s="$(printf '%s' "$r" | ok)"
  # already_reacted is a success for our purposes (idempotent)
  case "$s" in 1|0:already_reacted) return 0 ;; *) echo "react add $1 -> $s" >&2; return 1 ;; esac
}
do_remove() {
  local r; r="$(api reactions.remove -d "channel=$CH" -d "timestamp=$TS" -d "name=$1")"
  local s; s="$(printf '%s' "$r" | ok)"
  case "$s" in 1|0:no_reaction) return 0 ;; *) echo "react remove $1 -> $s" >&2; return 1 ;; esac
}

case "$CMD" in
  add)    [ -n "$EMOJI" ] || { echo "emoji required" >&2; exit 2; }; do_add "$EMOJI" && echo "ok" ;;
  remove) [ -n "$EMOJI" ] || { echo "emoji required" >&2; exit 2; }; do_remove "$EMOJI" && echo "ok" ;;
  get)
    api reactions.get -d "channel=$CH" -d "timestamp=$TS" | python3 -c '
import sys,json
d=json.load(sys.stdin)
m=d.get("message") or d.get("channel",{}).get("message") or {}
for r in m.get("reactions",[]): print(r.get("name",""))
' ;;
  state)
    [ -n "$EMOJI" ] || { echo "emoji required" >&2; exit 2; }
    for e in $STATE_EMOJIS; do [ "$e" = "$EMOJI" ] || do_remove "$e" || true; done
    do_add "$EMOJI" && echo "ok" ;;
  *) echo "unknown command: $CMD" >&2; exit 2 ;;
esac
