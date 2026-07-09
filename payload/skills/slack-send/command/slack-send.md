---
description: Send a Slack message or upload a file (DM/channel/thread) as yourself via the CC App token
argument-hint: <target: me | @user | #channel | ID> <message... | file_path> [thread_ts]
allowed-tools: Bash(~/.claude/skills/slack-send/scripts/send.sh:*), Bash(~/.claude/skills/slack-send/scripts/msg.sh:*)
---

Send to Slack using the `slack-send` skill (message or file).

Arguments given: `$ARGUMENTS`

Do this:
1. Parse `$ARGUMENTS`. First token = `target` (`me`, `@user`, `#channel`, or raw ID).
2. Decide action:
   - If any remaining token is a path to an **existing local file** → **file upload**:
     `~/.claude/skills/slack-send/scripts/send.sh "<file>" "<target>" "<comment?>" "<thread_ts?>"`
   - Otherwise → **message** (rest of args = text):
     `~/.claude/skills/slack-send/scripts/msg.sh "<target>" "<message>" "<thread_ts?>"`
3. Posting to a `#channel` is user-facing — if the channel wasn't clearly intended, confirm first.
4. Fallbacks:
   - `msg.sh` exit **3** (no token): offer (a) connect CC App via
     `~/.claude/skills/slack-send/install.sh`, or (b) send now via the built-in
     `slack_send_message` MCP tool (no file upload, connector identity). Ask which.
   - `send.sh` token/`NO_TOKEN` error: files need the CC App — MCP can't upload.
     Point the user to `install.sh`; optionally offer to post a message with a link instead.
5. On success relay the `OK ...` line + permalink. Never print the token.
