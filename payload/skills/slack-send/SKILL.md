---
name: slack-send
description: Send a Slack message OR upload a file to Slack (DM, channel, or thread reply) as yourself. Use when the user asks to "send a slack message", "dm X on slack", "post to #channel", "reply in this slack thread", "send this file to slack", "slack this file", or "dm me this file". Messages prefer the CC App token (posts as you) and fall back to the built-in Slack MCP connector if no token. Files REQUIRE the CC App token (the MCP connector cannot upload files) — if it's missing, prompt the user to install it.
---

# slack-send

One skill for both **messages** and **files** to Slack — DM, channel, or thread
reply, posted **as you** via the shared **CC File Sender** user token.

## Two actions

| Action | Script | No-token fallback |
|--------|--------|-------------------|
| **Message** (text) | `scripts/msg.sh` | ✅ fall back to Slack **MCP connector** (`slack_send_message`) |
| **File** (upload) | `scripts/send.sh` | ❌ none — MCP can't upload. Prompt user to install the CC App. |

## Decision logic (follow this)

1. **Message request** → run `msg.sh`. If it exits **3** (no token), don't fail:
   - Offer to **connect the CC App** (run `~/.claude/skills/slack-send/install.sh`
     once → posts as you, and unlocks file sending too), **or**
   - Send it now via the **MCP connector** `slack_send_message` instead (no setup;
     note it posts under the connector's identity and can't attach files).
   Ask which; proceed.
2. **File request** → run `send.sh`. If it errors with a token/`NO_TOKEN` problem:
   - The MCP connector **cannot upload files**, so there is no silent fallback.
   - Tell the user: to send files, connect the CC App once —
     `~/.claude/skills/slack-send/install.sh` (see `README.md` for the token step).
   - Offer the alternative of sending just a **message with a link** via the MCP
     connector, if a hosted URL exists.

## Usage

```bash
# message
~/.claude/skills/slack-send/scripts/msg.sh  <target> <message> [thread_ts]
# file
~/.claude/skills/slack-send/scripts/send.sh <file_path> <target> [comment] [thread_ts]
```

| `target` | meaning |
|----------|---------|
| `me` | DM yourself |
| `@username` | DM a user (username / display / real name) |
| `Uxxxxxxxx` | user id → DM |
| `#channel-name` or bare `channel-name` | a channel you're in |
| `Cxxxx` / `Dxxxx` / `Gxxxx` | raw channel/DM/group id |

- `thread_ts` (optional) — parent message ts to post/reply into a thread.
- Message text is Slack mrkdwn (`*bold*`, `_italic_`, `` `code` ``, `<url|label>`).
- `msg.sh` exit codes: `0` ok · `2` usage/resolve error · `3` **no token**.
- `send.sh` prints `OK sent ...` + permalink; `msg.sh` prints `OK message ... ts=<ts>` + permalink.

## Examples

```bash
msg.sh  me "build is green ✅"
msg.sh  @davit "can you check MR !42?"
msg.sh  "#dev-reports" "nightly run done"
send.sh ~/Desktop/report.pdf me "monthly report"
send.sh ./coverage.html "#dev-reports" "nightly coverage"
send.sh ./mr-review.html C0BEY904BNZ "full report" 1783423834.995569   # into a thread
```

## In Claude Code

```
/slack-send <message or file...>
```
The `/slack-send` command dispatches: if the first token after the target is a
path to an existing file, it uploads; otherwise it posts a message. You can also
just say *"dm @davit on slack: build is green"* or *"send ~/Desktop/x.pdf to #dev"*.

## Setup

Run once — a browser opens, click **Allow**, done (no admin page, no copy-paste):
```bash
~/.claude/skills/slack-send/install.sh
```
Writes `~/.slack-upload-token` (CC App **user** token `xoxp-`, chmod 600) and
`~/.slack-upload-owner` (your user id, for `me`). Both scripts share this config.
Fallback: `install.sh --manual` to paste a token. See `README.md`.

## Claude Desktop (chat)

Also runs as a local MCP server (`scripts/mcp_server.py`, zero-dep stdio) exposing
`slack_send_message` + `slack_send_file`. Register with `install.sh --desktop`
(merges into `claude_desktop_config.json`, restart Desktop). Local files only —
claude.ai web chat can't reach the local machine/token.

## Used by

- **review-pr-slack** — posts the verdict message (`msg.sh`) and uploads the HTML
  report into the same thread (`send.sh`).
