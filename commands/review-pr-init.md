---
description: Guided first-time setup for pr-review-loop — connect the PR platform (required) and, if wanted, Slack delivery and graphify. Ends by running the doctor.
---

Walk the user through setup interactively. Ask before installing or connecting
anything; nothing here is silent. Use the `AskUserQuestion` tool for each choice.

## 1. Snapshot the current state

Run the doctor first so you know what's already set up and only ask about gaps:

```bash
bash ~/.claude/skills/review-memory/scripts/doctor.sh
```

## 2. PR platform (required)

At least one is required — it's how reviews fetch PRs. If `gh` or `glab` already
shows authenticated in the doctor output, confirm and move on. Otherwise ask:

> **AskUserQuestion** — "Which PR platform do you review on?"
> options: GitHub (`gh`) · GitLab (`glab`) · Both

For each chosen platform not yet authenticated, give the exact steps and let the
user run them (do not run auth for them):
- GitHub: install `gh`, then `gh auth login`.
- GitLab: install `glab`, then `glab auth login`.

Re-check with `gh auth status` / `glab auth status` before continuing. If neither
can be set up, stop and say the plugin can't fetch PRs without one.

## 3. Slack delivery (optional)

Only needed for `/review-pr-slack` and the Slack watcher. Ask:

> **AskUserQuestion** — "Set up Slack delivery? (verdict message, HTML report upload, reaction state)"
> options:
> - "Yes — send-slack skill (recommended)" — posts as you, can upload the HTML
>   report and set reactions. Run `~/.claude/skills/slack-send/install.sh` and walk
>   the user through connecting the token.
> - "Yes — Slack MCP connector" — message-only; cannot upload files or (reliably)
>   set reactions. Tell the user to enable the Slack connector in their claude.ai
>   connector settings; note the report must then be attached manually.
> - "No, skip" — `/review-pr` and local reviews still work fully; skip Slack.

If they pick the send-slack skill, after install verify a token exists
(`~/.slack-upload-token` or `$SLACK_UPLOAD_TOKEN`).

## 4. graphify (optional)

Adds semantic review-memory recall; JSONL recall works without it. If the doctor
shows it missing, ask:

> **AskUserQuestion** — "Install graphify for semantic recall? (optional)"
> options: Yes · No (keep JSONL recall)

On yes: `bash ~/.claude/skills/review-memory/scripts/ensure-graphify.sh --force`.

## 5. Per-repo config (optional, only if run inside a repo)

If the working directory is a git repo, offer to write an editable config:

> **AskUserQuestion** — "Write a per-repo config (.review-memory/config.json)? Lets you set the loop's cycle cap, watch channel, and state emojis."
> options: Yes · No

On yes: `python3 ~/.claude/skills/review-memory/scripts/memory.py config . --init`,
then show the file and mention it should be committed.

## 6. Confirm

Re-run the doctor and summarize: what's ready, what was skipped (and that it's
optional), and the first command to try — `/review-pr <PR_URL>` for a one-off, or
`/loop 10m /review-pr-watch` once they've validated with `--dry-run`.
