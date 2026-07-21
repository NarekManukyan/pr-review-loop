# Prior comments — mine the MR/PR thread we don't post to

Both front-ends are **read-only** on GitLab/GitHub, so every note already on the MR/PR is
**external signal from someone else** — a human reviewer, a bot (CodeRabbit), the author.
Ignoring it is how we miss things a person already wrote down. Real case: on
`explorer-back!79/!82/!83` a human left `## AC status — not done` comments naming a sibling
table, a sibling struct, and an unmet criterion — all sitting in the thread while our panel
reviewed only the diff and reported "correct". This step ingests those notes and guarantees
we either **confirm** or **consciously dismiss** each one — never silently skip it.

This complements the Jira AC pass (Reviewer F): Jira has the *acceptance criteria*; the MR
thread often has a human's *AC verdict* and edge cases. Use both.

## 1. Fetch (front-end, read-only)

GitLab (per MR):
```bash
glab api "projects/<enc>/merge_requests/<N>/notes?sort=asc&per_page=100"       # discussion notes
glab api "projects/<enc>/merge_requests/<N>/discussions?per_page=100"          # threaded, carries position{new_path,new_line}
```
GitHub (per PR): `gh pr view <N> --json comments,reviews` + `gh api repos/<o>/<r>/pulls/<N>/comments` (inline).

Normalize each into: `{author, is_bot, file, line, body, created_at, resolved?}`. Position
(`file:line`) is on inline/diff notes only; thread-level notes have none.

## 2. Filter — keep signal, drop noise

- **Drop `system: true`** notes (label/assignee/status churn) entirely.
- **We never post here**, so there is no "our own" comment to filter — everything is external.
- **Classify by author:**
  - *human* — highest signal. Read in full.
  - *bot* (CodeRabbit, Danger, etc.) — leads, not truth. Collapse its auto-summary boilerplate
    (`<!-- generated -->`, review-stack banners); keep only concrete claims with a `file:line`.
- **Respect resolution but verify it:** a `resolved`/outdated thread is a hint it's handled,
  **not proof** — reconcile against HEAD anyway (U9: stale flags lie).

Write the survivors to `prior-comments.md` in the scratchpad, grouped human-first, each with
`author · file:line · the claim`. Pass this file to Reviewers **E** and **F** (and A–C when a
comment lands in their lane).

## 3. Reviewers treat comments as leads to VERIFY, not facts to echo

Every ingested comment is a hypothesis to test against HEAD — FACT vs ASSUMPTION applies to
*their* claims as much as ours:
- **Confirm** — reproduce it in code → it becomes a normal finding (cite `file:line`; credit
  is irrelevant, coverage is the point).
- **Refute** — the code shows it's already fixed / was never true → record as dismissed with
  the reason + `file:line`. "CodeRabbit said X" is not evidence; the code is.
- **Out of our lenses** — a product/design/QA point no persona owns → surface it verbatim in
  the overview rather than dropping it.
Never re-assert a comment the author already answered in-thread without engaging their answer
(same rule as `thread-context.md` developer replies).

## 4. Coverage reconciliation — the anti-miss guarantee

After the panel produces findings, run a **coverage check** over `prior-comments.md`: map every
external comment to exactly one of `also-found` (we independently found it too) / `confirmed`
(we verified it this round) / `refuted` (cite why) / `deferred-to-human` (out of scope). Any
comment that maps to **none** is a hole — go back and verify it before delivering.

Emit a compact **"Prior comments" block** in the report overview (and the Slack verdict when
non-empty):
```
Prior comments reconciled — 5 (3 human · 2 bot):
  ✓ confirmed  errors.go:44 tourTemplateErrorMappings missing sentinels (human, now P1)
  ✓ also-found reader.go:47 dead viewer_count field
  ✗ refuted    "N+1 in list" — batched at repository.go:210 (cite)
  ⚑ human-call  "AC3 scope" — product decision, surfaced to author
```
A `confirmed`/`also-found` external item is a normal finding and counts toward the verdict. The
value is the invariant: **nothing a human or bot already wrote on the MR leaves un-addressed.**

## Cost note

Fetching notes is one API call per MR and cheap. Verifying each is bounded by the count of
concrete `file:line` claims (usually a handful). Don't spawn a verifier per bot line — collapse
bot boilerplate first (step 2), then let E/F verify the concrete survivors on demand.
