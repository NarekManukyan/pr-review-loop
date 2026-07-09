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
4. End with a one-line verdict: ready to use, or the single most important thing to fix.
