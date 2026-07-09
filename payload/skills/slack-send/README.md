# slack-send

Send **messages** and **files** to Slack (DM, channel, or thread) straight from
Claude Code — posted **as you**.

- **Messages** use the CC App user token, and **fall back to the built-in Slack
  MCP connector** if you haven't set the token up.
- **Files** need the CC App token — the MCP connector *cannot upload files*. If
  the token is missing, the skill prompts you to connect it.

Files post as you (personal user token), so a report looks like you dragged it in
yourself.

---

## What you get

- `/slack-send <target> <message | file> [thread_ts]` — one command, auto-detects
  message vs file (a real file path → upload, else → message)
- Natural language: *"dm @davit on slack: build green"*, *"send ~/Desktop/x.pdf to #dev"*
- Used by **review-pr-slack** to post the verdict and attach the HTML report into
  the thread.

---

## Install (per person, ~1 min)

Grab the skill bundle anywhere (unzip / clone), then run:
```bash
cd slack-send && bash install.sh
```
(Use `bash install.sh` — unzipping can strip the executable bit, so `./install.sh`
may say "permission denied".)
That's it. The installer:
1. Copies the skill into `~/.claude/skills/slack-send/` and adds the `/slack-send` command
2. **Opens your browser to connect Slack** — just click **Allow**
3. Captures your personal token automatically and writes:
   - `~/.slack-upload-token` — your token (chmod 600)
   - `~/.slack-upload-owner` — your Slack user id (for `me`)

No app admin page, no copy-paste. You must be signed into the `m-oneteam` Slack in
your browser; the click grants a token that acts as **you**.

**Flags**
- `./install.sh --manual` — paste a `xoxp-` token yourself (if the browser flow can't run)
- `./install.sh xoxp-...` — use a token you already have
- `./install.sh --no-token` — install files only, connect later
- Env overrides: `CC_CLIENT_ID`, `CC_CLIENT_SECRET`, `CC_PORT` (default 53682)

Test:
```bash
~/.claude/skills/slack-send/scripts/msg.sh  me "hi"
~/.claude/skills/slack-send/scripts/send.sh ~/Desktop/anything.pdf me
```

---

## Use in Claude Desktop (chat)

The skill also runs as a local MCP server so **Claude Desktop chat** can send
messages/files as you (same token). **The normal `bash install.sh` auto-registers
it whenever Claude Desktop is detected** on your Mac — so a from-scratch install
sets up both Claude Code *and* Claude Desktop. It adds `slack-send` to
`~/Library/Application Support/Claude/claude_desktop_config.json` (existing servers
preserved, a `.bak` is written). **Restart Claude Desktop**, then in chat ask it to
*send a file/message to Slack* — it exposes `slack_send_message` and `slack_send_file`.

Flags: `--desktop` forces registration; `--no-desktop` skips it.

Notes:
- Needs Python 3 (preinstalled on macOS) — the server is dependency-free.
- Only reaches files on **your machine** (local MCP). claude.ai web chat can't use it.
- Requires the token (run without `--no-token`, or connect first).

## Usage (CLI / Claude Code)

```bash
scripts/msg.sh  <target> <message> [thread_ts]     # message
scripts/send.sh <file_path> <target> [comment] [thread_ts]   # file
```

| `target` | meaning |
|----------|---------|
| `me` | DM yourself |
| `@username` | DM a user (username / display / real name) |
| `Uxxxxxxxx` | user id → DM |
| `#channel-name` or `channel-name` | a channel you're in |
| `Cxxxx` / `Dxxxx` / `Gxxxx` | raw channel/DM/group id |

`thread_ts` = parent message ts to post into a thread.

### Examples
```bash
msg.sh  @davit "can you check MR !42?"
msg.sh  "#dev-reports" "nightly run done"
send.sh ~/Desktop/report.pdf me "monthly report"
send.sh ./mr-review.html C0BEY904BNZ "report" 1783423834.995569
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `channel not found` / `not_in_channel` | Join the channel, or pass the raw `Cxxxx` id. |
| Posts show as a **bot** | You saved the `xoxb-` token. Re-run `install.sh` with the **`xoxp-`** User token. |
| `NO_TOKEN` / can't upload file | Files need the CC App — run `install.sh`. MCP can't upload. |
| `token rejected` | Reinstall the app, grab a fresh `xoxp-`, re-run `install.sh`. |
| `'me' needs ... owner` | Re-run `install.sh`. |
| `permission denied` on `./install.sh` | Unzip stripped the exec bit — run `bash install.sh`. |
| `CERTIFICATE_VERIFY_FAILED` | Fixed — the token exchange uses `curl` (system certs). Make sure you're on the latest bundle. |

## Scopes (reference)
User scopes on the app; only `files:write` is strictly required, the rest enable
name/`@user`/`me`/channel lookup and messages:
```
files:write   chat:write   channels:read   groups:read   users:read   im:write
```

## Security
Token lives only in `~/.slack-upload-token` (chmod 600), never in git. It acts as
**you** — treat it like a password. Revoke by reinstalling the app (rotates token).
