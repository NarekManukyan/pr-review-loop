#!/usr/bin/env bash
# Post a Slack message via Web API (chat.postMessage), as the token owner (you).
# Usage: msg.sh <target> <message> [thread_ts]
#   target:    "me" | @username | Uxxxx (user id -> DM) | #channel-name | Cxxxx/Dxxxx/Gxxxx | bare channel name
#   thread_ts: optional parent message ts to reply in a thread
# Token: $SLACK_UPLOAD_TOKEN or ~/.slack-upload-token (the CC File Sender user token, xoxp-).
# Exit codes: 0 ok | 2 usage/resolve error | 3 no token (caller should suggest install)
set -euo pipefail

TARGET="${1:?target required (me | @user | #channel | ID)}"
MESSAGE="${2:?message text required}"
THREAD_TS="${3:-${SLACK_THREAD_TS:-}}"

TOKEN="${SLACK_UPLOAD_TOKEN:-}"
[ -z "$TOKEN" ] && [ -f "$HOME/.slack-upload-token" ] && TOKEN="$(cat "$HOME/.slack-upload-token")"
if [ -z "$TOKEN" ]; then
  echo "NO_TOKEN: no CC App token found (\$SLACK_UPLOAD_TOKEN or ~/.slack-upload-token)." >&2
  echo "Run the installer to connect: ~/.claude/skills/slack-send/install.sh" >&2
  exit 3
fi

api() { local m="$1"; shift; curl -s -X POST "https://slack.com/api/$m" -H "Authorization: Bearer $TOKEN" "$@"; }
jget() { python3 -c '
import sys,json
try:
    d=json.load(sys.stdin)
    for k in sys.argv[1:]:
        d=d[int(k)] if isinstance(d,list) else d[k]
    print(d if d is not None else "")
except Exception:
    print("")
' "$@"; }

owner_id() {
  local o="${SLACK_OWNER_ID:-}"
  [ -z "$o" ] && [ -f "$HOME/.slack-upload-owner" ] && o="$(cat "$HOME/.slack-upload-owner")"
  echo "$o"
}
open_dm() { api conversations.open --data-urlencode "users=$1" | jget channel id; }

find_channel() {
  local name="$1" cursor=""
  for _ in 1 2 3 4 5; do
    local resp cid
    resp=$(api conversations.list --data-urlencode "types=public_channel,private_channel" --data-urlencode "limit=1000" --data-urlencode "cursor=$cursor")
    cid=$(echo "$resp" | NAME="$name" python3 -c '
import sys,json,os
d=json.load(sys.stdin); n=os.environ["NAME"]
print(next((c["id"] for c in d.get("channels",[]) if c.get("name")==n),""))')
    [ -n "$cid" ] && { echo "$cid"; return; }
    cursor=$(echo "$resp" | jget response_metadata next_cursor)
    [ -z "$cursor" ] && break
  done
}

find_user() {
  local name="${1#@}" cursor=""
  for _ in 1 2 3 4 5; do
    local resp uid
    resp=$(api users.list --data-urlencode "limit=200" --data-urlencode "cursor=$cursor")
    uid=$(echo "$resp" | NAME="$name" python3 -c '
import sys,json,os
d=json.load(sys.stdin); n=os.environ["NAME"].lower()
def m(u):
    p=u.get("profile",{})
    return n in (u.get("name","").lower(),(p.get("display_name") or "").lower(),(p.get("real_name") or "").lower())
print(next((u["id"] for u in d.get("members",[]) if not u.get("deleted") and m(u)),""))')
    [ -n "$uid" ] && { echo "$uid"; return; }
    cursor=$(echo "$resp" | jget response_metadata next_cursor)
    [ -z "$cursor" ] && break
  done
}

CH=""
case "$TARGET" in
  me)        o="$(owner_id)"; [ -z "$o" ] && { echo "ERROR: 'me' needs SLACK_OWNER_ID or ~/.slack-upload-owner" >&2; exit 2; }; CH="$(open_dm "$o")" ;;
  U*)        CH="$(open_dm "$TARGET")" ;;
  C*|D*|G*)  CH="$TARGET" ;;
  @*)        uid="$(find_user "$TARGET")"; [ -z "$uid" ] && { echo "ERROR: user not found: $TARGET" >&2; exit 2; }; CH="$(open_dm "$uid")" ;;
  \#*)       CH="$(find_channel "${TARGET#\#}")"; [ -z "$CH" ] && { echo "ERROR: channel not found: $TARGET (join it or pass Cxxxx id)" >&2; exit 2; } ;;
  *)         CH="$(find_channel "$TARGET")"; [ -z "$CH" ] && { echo "ERROR: cannot resolve target: $TARGET" >&2; exit 2; } ;;
esac
[ -z "$CH" ] && { echo "ERROR: empty channel id for target $TARGET" >&2; exit 2; }

PAYLOAD=$(CHID="$CH" MSG="$MESSAGE" TTS="$THREAD_TS" python3 -c '
import json,os
p={"channel":os.environ["CHID"],"text":os.environ["MSG"]}
if os.environ.get("TTS"): p["thread_ts"]=os.environ["TTS"]
print(json.dumps(p))')
R=$(curl -s -X POST https://slack.com/api/chat.postMessage -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json; charset=utf-8" -d "$PAYLOAD")
echo "$R" | grep -q '"ok":true' || { echo "ERROR postMessage: $R" >&2; exit 2; }

TS=$(echo "$R" | jget ts)
POSTED_CH=$(echo "$R" | jget channel)
# build a permalink
LINK=$(api chat.getPermalink --data-urlencode "channel=$POSTED_CH" --data-urlencode "message_ts=$TS" | jget permalink)
echo "OK message -> $TARGET ($POSTED_CH) ts=$TS"
[ -n "$LINK" ] && echo "$LINK"
