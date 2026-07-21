---
description: Check that pr-review-loop is set up correctly — auth, skills, Slack token, graphify, shiki — and explain how to fix anything missing.
---

Run the setup self-check and interpret it for the user:

```bash
bash ~/.claude/skills/review-memory/scripts/doctor.sh
```

Then:

1. Show the PASS / WARN / FAIL results.
2. For each **FAIL**, give the exact fix (they block use):
   - python3 missing → install Python 3.
   - no gh/glab → install and authenticate (`gh auth login` / `glab auth login`).
3. For each **WARN**, say whether it matters for what the user actually does:
   - Slack token only matters for `/review-pr-slack` and the Slack watcher.
   - shiki only affects HTML report highlighting in Slack preview.
   - graphify is optional (JSONL recall works without it).
   - missing skills/commands on a marketplace install usually resolve after a
     session restart (the SessionStart hook syncs them); on a standalone install,
     re-run `install.sh`.
4. Note the **"review engine would load: …"** line — it shows which stack lens pack(s)
   the `review-core` resolver would apply in the current repo (or universal-only
   fallback). If `review-core` itself shows missing, reviews still run but only with
   universal lenses until it syncs (restart, or re-run `install.sh`).
5. **Jira routing live-check (Reviewer F / AC pass).** The script lists the configured
   `route → jira_site` map and how many Atlassian MCP servers are registered, but only a
   live MCP call proves a site is actually reachable. For each distinct `jira_site` in
   `~/.claude/skills/review-core/config/jira-routing.json`, call
   `getAccessibleAtlassianResources` on **every** connected Atlassian MCP server (there
   may be more than one, each a different account) and report, per site:
   - **reachable** — name the site + the account (`atlassianUserInfo`) that reaches it →
     PASS ("dz44-group MRs will pull ACs from `<site>` as `<email>`").
   - **registered but not reachable in this session** — the server is in `~/.claude.json`
     but its tools aren't loaded yet → tell them to **start a fresh session** (MCP servers
     connect at session start; one added mid-session won't appear until restart).
   - **no connected server reaches it** — the owning account isn't connected → tell them
     to add/authenticate an Atlassian MCP as that account (e.g. minitok site needs the
     `narek.manukyan@minitok.com` login), then restart. Until then that group's AC pass
     falls back to MR-description ACs (not wrong-account ACs).
   Optionally confirm end-to-end by fetching one known issue (e.g. `getJiraIssue` on the
   dz44 site for a `COM-*` key) — a summary coming back means Reviewer F is wired.
6. End with a one-line verdict: ready to use, or the single most important thing to fix.
