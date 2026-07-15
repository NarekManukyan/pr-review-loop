---
description: Assemble a stack-aware reviewer panel (Architecture · Correctness · Perf/Quality · Build&Analyze) and post a structured PR review with inline comments, an overview, and a fix prompt
argument-hint: <PR_URL>
---

You are orchestrating a code-review panel. The **review brain lives in the shared
`review-core` engine** — do not restate personas or stack rules here; load them:

> **Read the engine first:** `~/.claude/skills/review-core/SKILL.md` and its
> `references/` (`resolver.md`, `universal-lenses.md`, `personas.md`, `lenses/`).
> This command only handles **inline delivery** on GitHub/GitLab.

The panel is Reviewers **A (Architecture)**, **B (Correctness)**, **C (Perf/Quality)**,
and **D (Build & Analyze — CI parity + reachability)**, defined in
`review-core/references/personas.md`. Their focus, the universal lenses (U1–U12), and
the per-stack idioms are all supplied by the engine.

---

## Instructions

1. **Read `CLAUDE.md`** in the repo root and **every ADR** (`docs/adr/`, `docs/adrs/`,
   `.cursor/rules/*.mdc`) before anything. Apply them throughout; cite the specific
   ADR/rule in any finding it governs.

   **Review memory** — immediately after CLAUDE.md/ADRs, recall this repo's past
   outcomes (calibration only, never overrides CLAUDE.md/ADRs):
   ```bash
   python3 ~/.claude/skills/review-memory/scripts/memory.py recall . --area "<changed features / paths>"
   ```
   Honor prior deferrals; don't re-raise findings the author resolved/disputed/clarified
   unless the code materially changed; load `.review-memory/rules.md`. After the review
   (and any thread replies) is finalized, record it:
   ```bash
   python3 ~/.claude/skills/review-memory/scripts/memory.py record . --input decisions.json
   ```
   `decisions.json` = `{"stack","commit","date","entries":[{mr,file,line,category,severity,title,dev_resolution,rationale,reviewer,round}]}`;
   `dev_resolution` ∈ open|resolved|deferred|disputed|clarified. Omit `signature`
   (auto-derives). Full contract: the `review-memory` skill.

2. **Resolve the stack (engine step).** Follow `review-core/references/resolver.md` on
   the repo root: detect the base stack + library overlays, and load the matching
   `lenses/*.md` on top of the universal lenses. Print the one-line result, e.g.
   `Stack: Flutter · packs: _base-flutter + flutter-mobx · repo rules: CLAUDE.md, analysis_options.yaml, .review-memory`.
   Unknown stack → **universal-only** (still a full review). This replaces the old
   hardcoded Flutter checklist — the engine now supplies stack-appropriate rules
   (Go/Postgres, NestJS, Flutter-BLoC/MobX, …).

3. **Fetch and analyze the PR**: $ARGUMENTS

4. **Detect the review round** from existing review comments:
   - No prior review comments → **Round 1**. Proceed.
   - Existing review comments → **re-review (Round N)**. First:

     **4a. Fetch the FULL comment history of every thread** (not just the first
     comment) — developer replies change how a finding is treated. Skipping replies is a
     review error.
     ```bash
     # GitHub
     gh api graphql -f query='
     { repository(owner:"OWNER",name:"REPO") { pullRequest(number:N) {
         reviewThreads(first:50){ nodes { id isResolved path
           comments(first:20){ nodes { databaseId author{login} body createdAt } } } } } }'
     # GitLab
     glab api "projects/<url-encoded-path>/merge_requests/<N>/discussions?per_page=100"
     ```

     **4b. Classify each thread from BOTH code AND developer replies.** Identify the
     author of each reply — your own prior bot replies do NOT count as developer input.
     **Verify claims at HEAD, not from `resolved=true`** (universal lens U9): re-read the
     file at the head SHA; a "fixed" counts only if the code proves it — and check
     whether the fix landed in a **stacked MR**.

     | Signal in thread | Action |
     |---|---|
     | Code fixed / dev says "done" | Reply `✅ Resolved — <evidence>`. Resolve thread. |
     | Code unchanged, no dev reply | Reply `⚠️ Still unresolved — <reason>`. Do NOT resolve. |
     | "ignore / not in scope / later / intentional" | Acknowledge as **deferred**; if shipping the deferred state is risky, reply with concrete guardrails (gate the route, short-circuit, link a ticket). Resolve on that basis. |
     | Disagreed / asked a question | Respond substantively — concede with rationale, or re-explain with code citations. Do NOT auto-resolve. |

     Never mark "Still unresolved" while ignoring an author reply — address it or
     re-classify as deferred.

     **4c. Sweep for orphan author comments since your last review** (terse inline notes
     like `"use switch"`, `"rename"`) that sit outside your threads. Each becomes a
     Round-N finding, even two words long:
     ```bash
     LAST=$(gh api repos/OWNER/REPO/pulls/N/reviews --jq '[.[] | select(.user.login=="<your-bot-login>")] | max_by(.submitted_at) | .submitted_at')
     gh api repos/OWNER/REPO/pulls/N/comments --paginate \
       --jq ".[] | select(.created_at > \"$LAST\") | select(.user.login != \"<your-bot-login>\") | {id,path,line,body,diff_hunk}"
     ```

     **4d. Only after every prior thread AND orphan comment is handled** proceed to
     review the new diff.

   **How to resolve threads (required):**
   ```bash
   gh api -X POST repos/OWNER/REPO/pulls/N/comments/<comment_databaseId>/replies -f body="✅ Resolved"
   gh api graphql -f query='mutation { resolveReviewThread(input:{threadId:"<thread_id>"}){ thread{ isResolved } } }'
   # GitLab: glab api -X PUT ".../discussions/<id>?resolved=true"
   ```

5. **Run the panel.** Spawn Reviewers A/B/C **and D** (Build & Analyze — the inline path
   now runs D too, so compile/lint/CI/reachability blockers are caught, not just on the
   Slack path). Into every persona prompt inject, in precedence order: the universal
   lenses → the loaded stack `lenses/*.md` → repo CLAUDE.md+ADRs → repo linter config →
   `.review-memory` recall (+ thread context on re-reviews). Skip generated files per the
   loaded pack's "Generated / skip" list.

6. **Each reviewer leaves inline comments** in this format:
   ```
   [Reviewer X – Category] file : line N
   Severity: P0 | P1 | P2
   ---
   <concise explanation + why it matters; cite exact code and the rule/ADR/lens>
   ```
   Severity: **P0** crash/data-loss/security/broken feature · **P1** significant
   bug/arch violation/serious perf · **P2** smell/minor. Complexity findings must cite
   the measured value vs the repo's linter threshold (universal lens U11). A PR that
   **conflicts with its target** (verify with `git merge-tree`, not just the API flag —
   U9) is a P1 blocker and can never be Approve.

7. **After inline comments, post a top-level overview** (`gh pr comment <N> --repo
   OWNER/REPO --body "…"` / `glab mr note <N>`) — same text in terminal and on the PR.
   Sections: **Summary** · **Stack & packs loaded** (the resolver line) · **✅ Resolved
   since last round** · **📌 Deferred by author** (with guardrails) · **📝 Author
   follow-up comments** · **⚠️ Still Open from previous rounds** · **🆕 New P0** ·
   **🆕 New P1** · **🆕 New P2** · **Build & Analyze** (Reviewer D: compiles, CI gates
   run, pipeline status, reachability gaps) · **Complex Logic Flagged** · **Verdict**
   (`✅ Approve` / `⚠️ Approve with minor fixes` / `🔄 Request Changes`). Merge conflict
   OR broken build/CI OR any P0/P1 → Request Changes.

8. **Generate a Fix Prompt** inside the overview (fenced) — a self-contained prompt the
   developer pastes into Claude Code. Every finding line: `file:line` + what's wrong +
   the required end state (not just the symptom).
   ```
   --- FIX PROMPT ---
   You are a <stack> developer fixing code review findings in [PR title / branch] — Round [N].

   STEP 1 — read before touching code: CLAUDE.md (full) + every ADR. Open each referenced
   file, its callers, and related tests. Understand intent before changing anything.

   STEP 2 — fix each finding at the ROOT CAUSE. Do NOT: add a comment/TODO and call it
   fixed; rename/reformat to look addressed; silence it (`// ignore:`, empty catch,
   deleting the code/test that surfaced it); introduce a generic solution ignoring the
   project's patterns. INSTEAD change the actual logic/structure using the project's
   patterns (per CLAUDE.md + ADRs + the loaded stack conventions). Keep scope tight. If a
   finding is unclear or you think it's wrong, STOP and ask.

   Findings:
   Still unresolved from previous rounds:
   - [finding + file:line + required end state]
   New P0 (must fix before merge):
   - [finding + file:line + required end state]
   New P1 (should fix before merge):
   - [finding + file:line + required end state]
   New P2 (fix when convenient):
   - [finding + file:line + required end state]
   Complex logic to verify (confirm correct or fix):
   - [function + file:line + the specific concern]

   STEP 3 — verify with the repo's REAL CI commands (formatter/linter/analyzer/tests,
   incl. build tags — see the stack pack's CI gates). Not done until it compiles and the
   pipeline's checks pass. Per finding, state what changed, why, and which rule/ADR/lens
   it satisfies. If anything is left unfixed, say so and why.
   --- END FIX PROMPT ---
   ```
