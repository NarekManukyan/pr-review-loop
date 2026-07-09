# review-pr-slack — Claude Code skill

3-persona AI review panel for GitLab MRs / GitHub PRs that **never posts comments
on GitLab/GitHub**. Instead it produces:

- a single **GitHub-style HTML report** — annotated diffs (only the hunks that
  have comments), threaded inline findings from 3 reviewer personas
  (Architecture / Correctness / Performance) plus a **Build & Analyze** check
  (compiles? analyzer errors/warnings — run in an isolated git worktree),
  severity levels P0–P2, per-MR verdicts with build status, and copy-paste
  **Fix Prompts** for Claude Code. Syntax highlighting is baked in (shiki), so
  the file previews nicely inside Slack.
- a short **verdicts-only Slack message** — sent as a DM to the MR author, or as
  a thread reply if you give it a Slack message URL. It always shows you the
  resolved recipient and asks for confirmation before sending.

## Install

### Option A — one command

```bash
unzip review-pr-slack.zip && ./review-pr-slack/install.sh
```

### Option B — let Claude do it

Put the zip anywhere (e.g. `~/Downloads`) and paste this into Claude Code:

> Install the Claude Code skill from ~/Downloads/review-pr-slack.zip:
> unzip it, copy the review-pr-slack folder into ~/.claude/skills/,
> and run `npm install` inside ~/.claude/skills/review-pr-slack/scripts.

Restart Claude Code (new session) — the skill auto-registers.

## Prerequisites

- **glab** CLI authenticated for your GitLab (`glab auth status`) — or **gh** for GitHub
- **Slack connector** enabled in Claude Code (claude.ai → connectors); used to
  look up the author and send the message. Claude cannot upload files to Slack —
  you drag the HTML into the thread yourself.
- **node + npm** (optional but recommended) — bakes syntax highlighting into the
  report at build time. Without it the report falls back to CDN highlighting,
  which works in browsers but not in Slack's sandboxed preview.

## Usage

```
/review-pr-slack https://gitlab.com/<group>/<repo>/-/merge_requests/123
```

Multiple MRs at once are fine. You can also just give it a **Slack message
URL** — it reads the message and the whole thread under it, extracts every MR
link, and posts the verdict back as a reply in that same thread. On repeat runs
it also reads developer replies in the thread: "fixed" claims are verified
against the code, deferrals are honored with guardrails, disagreements get a
substantive response — shown as a "💬 Thread follow-ups" section in the report:

```
/review-pr-slack https://<workspace>.slack.com/archives/C0XXXX/p1234567890123456
```

What happens:

1. Fetches MR metadata + diffs (read-only), skips generated files.
2. Reads the repo's CLAUDE.md and applies its review standards (FACT vs
   ASSUMPTION: only provable findings become comments).
3. Runs 4 agents in parallel — 3 reviewers plus a build/analyzer check on an
   isolated worktree; overlapping findings are merged into one thread with
   "+1" replies, build errors become P0s, warning counts land in the verdict.
4. Builds `mr-review.html` and copies it to your Desktop.
5. Shows you the Slack recipient → you confirm → sends the short verdict
   message. You then drag the HTML file into the same thread.

## Notes for non-Flutter repos

The reviewer personas adapt to the stack automatically (prompt templates are
parameterized — see `references/reviewer-prompts.md`). The generated-file skip
list defaults to Flutter/Dart globs plus common lockfiles; the skill also picks
up your repo's own CLAUDE.md generated-file list if one exists. For a BE repo
you may want to extend the list in SKILL.md (§ Hard rules) with your codegen
outputs (e.g. `*.pb.go`, `openapi/generated/**`).

## Contents

```
review-pr-slack/
├── SKILL.md                        # the workflow Claude follows
├── install.sh
├── references/reviewer-prompts.md  # persona prompts, merge rules, Slack templates
└── scripts/
    ├── build_html.py               # HTML report generator (python3, stdlib only)
    ├── highlight.mjs               # build-time shiki highlighter (node)
    └── package.json                # shiki dependency
```
