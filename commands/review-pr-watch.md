---
description: One poll cycle of the /review-pr watcher — find PRs where you're a requested reviewer (or the head advanced since your last review) and run the next review round. Wrap in /loop to run continuously.
argument-hint: "[owner/repo]  (defaults to the current repo)"
---

Run **one** watch cycle that drives `/review-pr` for PRs needing a (re-)review.
Target: $ARGUMENTS (default: the current repo's remote).

"Developer requested review again" is detected two ways, both handled here:
- you are a **requested reviewer** (covers an explicit re-request), and
- the PR **head advanced** since your last review (new commits pushed).

State lives in review memory (`memory.py mark-reviewed` / `was-reviewed`), keyed by
`PR number + head commit`, so a PR is reviewed **once per head** — the next round
fires only when new commits land or a re-request produces a new head. A bare
re-request with **no new commits is intentionally skipped**: nothing changed to
review, so re-reviewing the identical head would just repeat the last round.

## Steps

1. **Resolve platform + repo.** GitHub → `gh`; GitLab → `glab`. Default to the
   current repo (`git remote`), or use `$ARGUMENTS` if given.

2. **List candidate PRs** (open, awaiting your review):
   - GitHub:
     ```bash
     gh pr list --state open --search "review-requested:@me" \
       --json number,headRefOid,url,title,updatedAt
     ```
     Also include PRs you have reviewed before whose head changed:
     `gh pr list --state open --author "@me" ...` is NOT it — use the reviewer
     search above plus any PR the developer re-requested.
   - GitLab:
     ```bash
     glab mr list --reviewer=@me -F json   # number, sha, web_url, title
     ```

3. **Filter to work (cap at 3 per cycle**; next cycle continues):
   For each candidate get its head commit `<sha>`, then:
   ```bash
   python3 ~/.claude/skills/review-memory/scripts/memory.py was-reviewed . --pr <number> --commit <sha>
   ```
   Exit 0 (`yes`) → already reviewed at this head, **skip**. Exit 1 (`no`) → needs
   a (re-)review.

4. **For each PR that needs review, run `/review-pr <url>`** — the full panel
   review (it detects the round from existing PR comments, recalls review memory,
   posts inline, records outcomes). It is the same command a human runs; the
   watcher just invokes it unattended.

5. **Mark it reviewed** so this head isn't reviewed twice:
   ```bash
   python3 ~/.claude/skills/review-memory/scripts/memory.py mark-reviewed . --pr <number> --commit <sha> --round <N>
   ```

6. **Unattended-run rules:** the `/loop` invocation is the standing authorization —
   proceed without interactive confirmation, but keep every `/review-pr` guardrail
   (FACT-vs-ASSUMPTION, skip generated files, review memory recall/record, no
   speculative comments). Nothing to do → say "no PRs awaiting review this cycle".

Run continuously with, e.g.:

```
/loop 10m /review-pr-watch
```

Report one line per PR handled (number, round, verdict), or the idle message.
