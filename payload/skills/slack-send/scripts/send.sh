#!/usr/bin/env bash
# Upload a file to Slack via Web API (files.uploadV2 flow).
# Usage: send.sh <file_path> <target> [comment] [thread_ts]
#   target:    "me" | @username | Uxxxx (user id -> DM) | #channel-name | Cxxxx/Dxxxx/Gxxxx (channel id) | bare channel name
#   thread_ts: optional parent message ts (e.g. 1783423834.995569) to post the file INTO that thread
# Token read from $SLACK_UPLOAD_TOKEN or ~/.slack-upload-token
set -euo pipefail

FILE="${1:?file path required}"
TARGET="${2:?target required (me | @user | #channel | ID)}"
COMMENT="${3:-}"
THREAD_TS="${4:-${SLACK_THREAD_TS:-}}"

[ -f "$FILE" ] || { echo "ERROR: file not found: $FILE" >&2; exit 1; }

TOKEN="${SLACK_UPLOAD_TOKEN:-}"
[ -z "$TOKEN" ] && [ -f "$HOME/.slack-upload-token" ] && TOKEN="$(cat "$HOME/.slack-upload-token")"
[ -z "$TOKEN" ] && { echo "ERROR: no token (set SLACK_UPLOAD_TOKEN or ~/.slack-upload-token)" >&2; exit 1; }

api() { local m="$1"; shift; curl -s -X POST "https://slack.com/api/$m" -H "Authorization: Bearer $TOKEN" "$@"; }

# jget <keys...> : navigate nested dict/list, print value or empty on any miss
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

owner_id() { # human owner for "me" (bot token's auth.test returns the BOT, not you)
  local o="${SLACK_OWNER_ID:-}"
  [ -z "$o" ] && [ -f "$HOME/.slack-upload-owner" ] && o="$(cat "$HOME/.slack-upload-owner")"
  echo "$o"
}
open_dm() { api conversations.open --data-urlencode "users=$1" | jget channel id; }

find_channel() { # by name (no leading #)
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

find_user() { # by @username / display / real name -> user id
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
  me)        o="$(owner_id)"; [ -z "$o" ] && { echo "ERROR: 'me' needs SLACK_OWNER_ID or ~/.slack-upload-owner (your Uxxxx id)" >&2; exit 1; }; CH="$(open_dm "$o")" ;;
  U*)        CH="$(open_dm "$TARGET")" ;;
  C*|D*|G*)  CH="$TARGET" ;;
  @*)        uid="$(find_user "$TARGET")"; [ -z "$uid" ] && { echo "ERROR: user not found: $TARGET" >&2; exit 1; }; CH="$(open_dm "$uid")" ;;
  \#*)       CH="$(find_channel "${TARGET#\#}")"; [ -z "$CH" ] && { echo "ERROR: channel not found: $TARGET (bot may need /invite)" >&2; exit 1; } ;;
  *)         CH="$(find_channel "$TARGET")"; [ -z "$CH" ] && { echo "ERROR: cannot resolve target: $TARGET" >&2; exit 1; } ;;
esac
[ -z "$CH" ] && { echo "ERROR: empty channel id for target $TARGET" >&2; exit 1; }

LEN=$(stat -f%z "$FILE" 2>/dev/null || stat -c%s "$FILE")
NAME=$(basename "$FILE")

R1=$(api files.getUploadURLExternal --data-urlencode "filename=$NAME" --data-urlencode "length=$LEN")
echo "$R1" | grep -q '"ok":true' || { echo "ERROR getUploadURL: $R1" >&2; exit 1; }
UPLOAD_URL=$(echo "$R1" | jget upload_url)
FILE_ID=$(echo "$R1" | jget file_id)

curl -s -X POST "$UPLOAD_URL" -F "file=@$FILE" >/dev/null

PAYLOAD=$(FID="$FILE_ID" FNAME="$NAME" CHID="$CH" CMT="$COMMENT" TTS="$THREAD_TS" python3 -c '
import json,os
p={"files":[{"id":os.environ["FID"],"title":os.environ["FNAME"]}],"channel_id":os.environ["CHID"],"initial_comment":os.environ["CMT"]}
if os.environ.get("TTS"): p["thread_ts"]=os.environ["TTS"]
print(json.dumps(p))')
R3=$(curl -s -X POST https://slack.com/api/files.completeUploadExternal -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json; charset=utf-8" -d "$PAYLOAD")
echo "$R3" | grep -q '"ok":true' || { echo "ERROR complete: $R3" >&2; exit 1; }

PERMALINK=$(echo "$R3" | jget files 0 permalink)
echo "OK sent '$NAME' -> $TARGET ($CH)"
echo "$PERMALINK"
