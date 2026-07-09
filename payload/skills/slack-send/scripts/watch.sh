#!/usr/bin/env bash
# Scan a Slack channel for PR-review work, as the token owner. Emits JSON the
# review-pr-slack watcher reasons over. Reactions ARE the state machine:
#   (no state emoji) = not yet reviewed · eyes = in progress ·
#   white_check_mark/wrench = reviewed (verdict posted).
#
# Usage: watch.sh <channel> [--limit N] [--owner-only]
#   <channel>: Cxxxx id, or #name / name (resolved via conversations.list).
# Output: JSON array, one object per top-level message that contains a PR/MR URL:
#   {ts, user, text, urls:[...], state:"new|in_progress|reviewed",
#    reactions:[...], reply_count, last_reply_ts, last_reply_user,
#    reviewed_ts:"<ts of newest verdict-ish>"}
# `state` = new (no eyes/checkmark/wrench), in_progress (eyes), reviewed (checkmark/wrench).
# A "next round" candidate = state==reviewed AND last_reply_ts > (verdict time) AND
#   last_reply_user == the PR author (the watcher confirms intent via slack_read_thread).
# Token: $SLACK_UPLOAD_TOKEN or ~/.slack-upload-token. Exit: 0 ok | 2 usage | 3 no token.
set -euo pipefail

CH_IN="${1:?usage: watch.sh <channel> [--limit N]}"
LIMIT=50
shift || true
while [ $# -gt 0 ]; do
  case "$1" in
    --limit) LIMIT="${2:?}"; shift 2 ;;
    --owner-only) shift ;;
    *) shift ;;
  esac
done

TOKEN="${SLACK_UPLOAD_TOKEN:-}"
[ -z "$TOKEN" ] && [ -f "$HOME/.slack-upload-token" ] && TOKEN="$(cat "$HOME/.slack-upload-token")"
[ -z "$TOKEN" ] && { echo "NO_TOKEN: run slack-send/install.sh" >&2; exit 3; }

api() { local m="$1"; shift; curl -s -G "https://slack.com/api/$m" -H "Authorization: Bearer $TOKEN" "$@"; }

# resolve channel name -> id if needed
CH="$CH_IN"
case "$CH_IN" in
  C*|G*|D*) : ;;
  *)
    NAME="${CH_IN#\#}"
    CH="$(api conversations.list -d "types=public_channel,private_channel" -d "limit=1000" \
      | python3 -c 'import sys,json;d=json.load(sys.stdin);n=sys.argv[1]
print(next((c["id"] for c in d.get("channels",[]) if c.get("name")==n),""))' "$NAME")"
    [ -z "$CH" ] && { echo "ERROR: channel not found: $CH_IN" >&2; exit 2; }
    ;;
esac

api conversations.history -d "channel=$CH" -d "limit=$LIMIT" | python3 -c '
import sys, json, re
d = json.load(sys.stdin)
if not d.get("ok"):
    sys.stderr.write("history error: %s\n" % d.get("error","")); sys.exit(2)
URL = re.compile(r"https?://[^\s|>]+/(?:-/merge_requests|merge_requests|pull)/\d+")
STATE = {"eyes":"in_progress","white_check_mark":"reviewed","wrench":"reviewed","rotating_light":"reviewed"}
out = []
for m in d.get("messages", []):
    text = m.get("text","")
    urls = sorted(set(URL.findall(text)))
    if not urls:
        continue
    names = [r.get("name","") for r in m.get("reactions",[])]
    state = "new"
    for n in names:
        if n in STATE:
            state = STATE[n]; break
    out.append({
        "ts": m.get("ts"),
        "user": m.get("user",""),
        "text": text[:280],
        "urls": urls,
        "state": state,
        "reactions": names,
        "reply_count": m.get("reply_count", 0),
        "last_reply_ts": (m.get("latest_reply") or ""),
    })
print(json.dumps(out, ensure_ascii=False))
'
