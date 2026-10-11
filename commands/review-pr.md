---
description: Assemble a stack-aware reviewer panel (Architecture · Correctness · Perf/Quality · Build&Analyze) and post a structured PR review with inline comments, an overview, and a fix prompt
argument-hint: <PR_URL> [--fork]
---

You are orchestrating a code-review panel. The **review brain lives in the shared
`review-core` engine** — do not restate personas or stack rules here; load them:

> **Read the engine first:** `~/.claude/skills/review-core/SKILL.md` and its
> `references/` (`resolver.md`, `universal-lenses.md`, `personas.md`, `stack-mode.md`,
> `lenses/`). This command only handles **inline delivery** on GitHub/GitLab.

The panel is Reviewers **A (Architecture)**, **B (Correctness)**, **C (Perf/Quality)**,
**D (Build & CI parity — spawn with `model: 'haiku'`, it is mechanical)**, and
**E (Seams & Blast Radius — U5/U13/U14: is the new thing wired, drained like its
siblings, consistent with its neighbours?)**, defined in
`review-core/references/personas.md`. Their focus, the universal lenses (U1–U14), and
the per-stack idioms are all supplied by the engine.

**Material contract — packets, not fetching.** The panel's material is built in code
before any seat starts (`build-packets.py`, step 5): every changed file with head-side
line numbers (whole file while the budget lasts, otherwise its changed regions), the repo
rules, the likely reads outside the diff, and each seat's own persona + lens slice. Seats
still owe the reads in `personas.md` § "Reading the code" — the packet covers most of
them, and the rest are batched into one or two turns. Findings are not limited to changed
files. Generated files are skipped and listed; any file shown only as changed regions is
listed in the packet manifest — **name those in the overview**, a partly-read file is a
known gap.

Why: measured on two real PRs, each seat spent 17–51 turns fetching material one tool
call per turn, re-sending a context that grew from 12k to 80–130k every turn. Cost is
turns × context, so the fetching — not the reasoning — was ~90% of the tokens. With
packets a seat takes 4–9 turns; tokens per review fell by more than half (9.6M → 4.0–4.5M
on the same two PRs) at the same quality.

---

**Flags** (anywhere in `$ARGUMENTS`; the PR URL is the argument that is not a flag):

| Flag | Seat mode | When |
|---|---|---|
| *(none)* | **packet** — each seat is a `review-panel` agent that reads the packet itself | default: the best results per run in the benchmark |
| `--fork` | **fork** — you read the packet once, seats are forks of you | ~40% cheaper and faster; slightly lower recall in the benchmark (6 vs 8–9 of 14 bugs over 2 PRs) — use it for routine PRs, re-reviews and two-pass runs |

A repo can make fork its default with `"seat_mode": "fork"` in
`.review-memory/config.json`; `--packet` forces the default back for one run. Print the
mode in the resolver line (`… · seats: packet|fork`).

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
   `decisions.json` = `{"stack","commit","date","entries":[{mr,file,line,category,severity,title,dev_resolution,rationale,reviewer,round}],"reviews":[{mr,round,verdict,head_sha,p0,p1,p2,build,conflicts}]}`.
   **Always emit the `reviews` roll-up** — one per reviewed MR, canonical findings only —
   or the verdict is lost and `/review-pr-stats` cannot count approved vs request-changes;
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

   **Detect the stack and compute its tip.** Check whether this PR's **target branch is
   another open PR's source branch** (a stacked chain). If it is, resolve the **stack
   tip** — the source branch of the last PR in the chain (`origin/<source-branch>` of the
   PR nobody targets) — and **pass that ref to every reviewer** in the common context
   block, e.g. `Stack chain: !54 → !55 → !57 · stack tip: origin/feat/delivery-config`.
   Each reviewer otherwise sees only its own merge-base: on a real 16-PR chain, four
   foundation PRs were marked down for components the very next PR wires up. Per
   `personas.md` § "Reading the code", any "not wired / not registered / no caller /
   never published / does not exist" finding MUST be checked against the tip — by
   **reading** the code there, never by grepping for an assumed symbol name — before it
   is reported.

   **A detected chain switches the whole review to stack mode — follow
   `review-core/references/stack-mode.md`.** Emit the chain map
   (`Stack detected: !41 → … → !53 (10 MRs, tip = …)`), then **ask the user the merge
   policy once** (AskUserQuestion — **atomic** = whole chain merges together → full stack
   mode; **piecemeal** = each MR merges to `main` separately → stack-level review *plus* a
   per-MR build gate answering only "does this MR alone leave `main` compiling?"). **Never
   guess the policy** — it is what makes stack-level review correct: if MRs land one at a
   time, the intermediate states really do reach `main`. In stack mode the panel reviews
   the **cumulative diff** `git merge-base <main> <tip>`…`<tip>` as ONE unit, findings are
   attributed back to the introducing MR via `scripts/attribute-findings.sh`, and the
   stack gets **one verdict** (each MR gets a short note pointing at it, not its own).
   Reviewing MR-by-MR is what produced 18 findings a later MR in the same chain had
   already fixed. A PR targeting `main` with no children is **independent** — unchanged
   per-PR path below.

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

   **4e. Read the task (ticket + acceptance criteria).** Extract the ticket key from the
   PR title or source branch (`/\b[A-Z]{2,}-\d+\b/`, e.g. `[COM-810]`, `MONE-909`). If
   present, route to the right Jira and fetch the issue per
   `review-core/references/spec-ac.md` + `config/jira-routing.json` (by GitLab/GitHub
   group; matches on Jira **site host**, so multiple Jira accounts coexist and the correct
   one is picked per repo). Pull the acceptance criteria (Jira ACs, else an AC/"Done when"
   section in the PR description). This is what Reviewer F needs; no key and no
   description ACs → skip F. Reading existing PR *comments* is already covered by step 4 —
   4e is only the **task/spec** side.

   **How to resolve threads (required):**
   ```bash
   gh api -X POST repos/OWNER/REPO/pulls/N/comments/<comment_databaseId>/replies -f body="✅ Resolved"
   gh api graphql -f query='mutation { resolveReviewThread(input:{threadId:"<thread_id>"}){ thread{ isResolved } } }'
   # GitLab: glab api -X PUT ".../discussions/<id>?resolved=true"
   ```

5. **Run the panel.**

   **5a. Start the build gate (Reviewer D), in the shell's background** — it is a script
   now, zero tokens, and it finishes while the seats work:
   ```bash
   nohup python3 ~/.claude/skills/review-core/scripts/build-gate.py --repo <checkout> \
     --head <head_sha> --base <merge_base> --pr-url <PR_URL> \
     --scratch <scratch-dir> --out <scratch>/build.json > <scratch>/build.log 2>&1 &
   ```
   It resolves the pinned toolchain, runs install → codegen → analyze → format (changed
   files) → the tests related to the change, records the PR's own pipeline status, and
   writes Reviewer D's build record plus findings. A repo pins its exact gates with
   `"build_gate": [{"name","cmd"}]` in `.review-memory/config.json`. Fall back to the
   `review-build` agent (haiku) only when the record says no gates exist for the stack.

   **5b. Build the packets:**
   ```bash
   python3 ~/.claude/skills/review-core/scripts/build-packets.py --repo <checkout> \
     --base <merge_base> --head <head_sha> --out <scratch>/packets \
     --pack <each lens file the resolver loaded, e.g. lenses/_base-flutter.md>
   ```

   **5c. Spawn the seats** — Reviewers A/B/C **and E** (and **F** when 4e found a ticket
   key or PR-description ACs — pass it the ACs), as several Agent calls in ONE message.
   How depends on the seat mode (see **Flags**).

   **Packet mode (default)** — spawn each seat with `subagent_type: 'review-panel'`; it
   reads the packet itself. The prompt is short — the packet carries the material:
   > You are Reviewer `<X>`. In your first turn, Read every `<scratch>/packets/common-*.md`
   > file and `<scratch>/packets/seat-<X>.md` — all in that one turn, as parallel Read
   > calls. Follow the packet's cost rule (≤ 2 more turns of batched reads, ≤ 15 tool
   > calls). `.review-memory` recall: `<recall lines>`. Return findings JSON.

   **Fork mode (`--fork`, or `seat_mode: fork`)** — needs the Agent tool to accept
   `subagent_type: 'fork'` (Claude Code with `CLAUDE_CODE_FORK_SUBAGENT=1`). If it does
   not, say so in one line and use packet mode — never fail the review over it. Read
   every `<scratch>/packets/common-*.md` yourself, in one turn of parallel Reads, and read
   nothing else before spawning. Then spawn each seat as a **fork**, prompt:
   > You are Reviewer `<X>`. Read `<scratch>/packets/seat-<X>.md` — your persona and
   > lenses. The review packet is already in your context. Cost rule: ≤ 2 more turns of
   > batched reads, ≤ 15 tool calls. `.review-memory` recall: `<recall lines>`. Return
   > findings JSON only.

   A fork inherits your context, so the packet is written to the cache **once** and every
   seat reads it at a fraction of the price; in packet mode each seat writes its own copy,
   and cache writes cost ~25× a cache read. Measured on two PRs vs packet mode: −40% cost
   ($11.48 → $6.96), −15% time, 22 vs 26 real issues and 6 vs 8 real bugs. Anything you
   read after the packet and before the spawn, every fork pays for — so spawn right after.

   Repo linter config and review-memory recall go in the prompt (they are short); the
   universal lenses, stack packs, CLAUDE.md/AGENTS.md and ADR index are already in the
   packet, in the same precedence order (repo rules outrank packs). F returns per-AC
   **done / partial / not-done** with a `file:line`; a `partial`/`not-done` AC is a P1
   (ticket not delivered) and posts as a normal inline/overview finding. **Never spawn a
   reviewer as `general-purpose`** — it re-sends ~100 unused MCP tool schemas every turn.
   The plugin's agents carry only `Read, Grep, Glob, Bash`, which is all a reviewer uses.
   When the seats return, read `<scratch>/build.json` (wait for it if the gate is still
   running) and merge its findings and build record as Reviewer D's.

5d. **Verify findings before posting** — follow `review-core/references/verify-findings.md`.
   **Re-locate** every raw finding with
   `~/.claude/skills/review-core/scripts/relocate-findings.py` (`--ref` = head,
   `--base` = merge-base; stack tip and its merge-base in stack mode), *then* merge &
   dedupe on the corrected lines, *then* — **only if any canonical finding came back
   `not_found`, `fuzzy` or `no_snippet`** — spawn one **`review-filter`** agent
   (`model: 'haiku'`) on just those findings. Snippets that matched the code exactly are
   already grounded; on a benchmark of two PRs the filter dropped nothing from them. It
   drops only findings the code proves wrong and never a P0/P1. Post the survivors; list the dropped ones in the overview
   under **Filtered by fact-check** with their evidence. Skip the filter for findings
   carried over from earlier rounds.

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

   **Posting an inline comment on GitLab — the exact call.** A comment only anchors to
   the diff when GitLab returns `"type": "DiffNote"`. Two encodings look like they work
   and silently do not:

   | Attempt | Result |
   |---|---|
   | `glab api -f "position[new_line]=52" …` | **201, but `type: DiscussionNote`** — a plain MR-level note. `-f` does not encode nested objects. |
   | `glab api --input body.json` | **HTTP 415** `The provided content-type '' is not supported.` |
   | `glab api -H "Content-Type: application/json" --input body.json` | ✅ `type: DiffNote` |

   The whole fix is the `-H` header. `line_code` and `line_range` are **not** required
   for single-line comments, despite what the 400 error text suggests.

   ```bash
   # diff_refs come from the MR itself — each MR in a stack has its own set
   glab api --repo "$REPO" "projects/:id/merge_requests/$IID" --jq .diff_refs
   cat > /tmp/note.json <<'JSON'
   { "body": "…",
     "position": { "position_type": "text",
       "base_sha": "…", "start_sha": "…", "head_sha": "…",
       "new_path": "path/to/file.dart", "old_path": "path/to/file.dart",
       "new_line": 52 } }
   JSON
   glab api --repo "$REPO" -X POST "projects/:id/merge_requests/$IID/discussions" \
     -H "Content-Type: application/json" --input /tmp/note.json
   ```

   `new_line` only for an **added** line; add `old_line` too for an unchanged **context**
   line inside a hunk. Always assert `type == "DiffNote"` on the response — a `201` alone
   does not mean it anchored.

   **A line outside the MR's diff hunks cannot anchor at all**, so post those as
   MR-level notes with `` `path` : line N `` in the body. Expect this for: pre-existing
   code (which is most `UNKNOWN` rows from `attribute-findings.sh`), files marked
   `binary` in `.gitattributes` (`.arb` localization files commonly are — they produce no
   hunks), and generated files the caps skipped. Compute anchorability up front by
   parsing `…/merge_requests/$IID/diffs` hunk headers rather than discovering it per
   POST — `relocate-findings.py` (step 5d) already did: its `anchor` field is `added`
   (post `new_line`), `context` (post `new_line` + the script's `old_line`) or `outside`/`no_diff`
   (MR-level note). On a real 2-MR stack this split was 16 inline / 12 MR-level.

   **Post the anchored note before deleting any note it replaces**, so a failure cannot
   drop a finding.

7. **After inline comments, post a top-level overview** (`gh pr comment <N> --repo
   OWNER/REPO --body "…"` / `glab mr note <N>`) — same text in terminal and on the PR.
   Sections: **Summary** · **Stack & packs loaded** (the resolver line) · **✅ Resolved
   since last round** · **📌 Deferred by author** (with guardrails) · **📝 Author
   follow-up comments** · **⚠️ Still Open from previous rounds** · **🆕 New P0** ·
   **🆕 New P1** · **🆕 New P2** · **Build & CI** (Reviewer D: compiles, CI gates run,
   pipeline status) · **Seams** (Reviewer E: reachability / lifecycle / sibling-parity
   gaps) · **Filtered by fact-check** (step 5d drops: title, `file:line`, ground,
   evidence — omit when empty) · **Skipped files** (anything the caps dropped — a known gap, name it) ·
   **Complex Logic Flagged** · **Verdict**
   (`✅ Approve` / `⚠️ Approve with minor fixes` / `🔄 Request Changes`). Merge conflict
   OR broken build/CI **OR an unverified build** OR any P0/P1 → Request Changes. An
   **unverified** build — Reviewer D returning `"compiles": null` on an open PR because
   the toolchain would not resolve, the install failed, or the analyzer could not run —
   blocks Approve exactly as a broken one does (verdict `🔄 Request Changes — build ⚠️
   unverified`, plus D's P1 finding). "Couldn't verify" is never "passes". Already-merged
   PRs are the one exception: `null` there just means the check was skipped.

   **Map the verdict to a real review event — submit the platform's own
   approval/blocking state via the review call (empty `body`), not just verdict text in
   the overview:**
   - `🔄 Request Changes` → `event: REQUEST_CHANGES` (GitHub) / `unapprove` + the note
     (GitLab). Any P0/P1, merge conflict, or broken/unverified build lands here.
   - `✅ Approve` (clean — no open findings that need a fix) → `event: APPROVE` (GitHub
     `POST .../pulls/N/reviews {"event":"APPROVE"}`) / `glab mr approve` (GitLab).
     **A clean Approve MUST submit the actual APPROVE event** so the PR's `reviewDecision`
     flips to `APPROVED` and the green check shows — a verdict word in the overview is not
     an approval. On a re-review this APPROVE supersedes an earlier `CHANGES_REQUESTED`
     from the same account; verify with `gh pr view N --json reviewDecision`.
   - `⚠️ Approve with minor fixes` → `event: COMMENT` (GitHub) / note only, **do NOT
     approve** (GitLab). This verdict means fixes are still outstanding (P2s, optional
     nits), so it must NOT submit a formal APPROVE — leave the platform's approval state
     unset and let the author address the minor items.
   - **"if available" fallback (clean Approve only):** the APPROVE event can be
     unavailable — you authored the PR (GitHub forbids self-approval → the POST 422s), the
     token lacks the scope, or a branch rule blocks it. Then fall back to `event: COMMENT`,
     state the verdict in the overview, and add one line in **Verdict** naming why the
     formal approval could not be submitted (e.g. "self-approval not allowed"). Never
     silently drop a clean Approve to a bare comment without saying so.

   **In stack mode** (step 3) there is **one overview and one verdict for the whole
   stack**, posted on the tip PR. Add a **Stack** section: the chain map, the merge policy
   the user chose, and the per-MR finding counts from `attribute-findings.sh` (plus any
   `UNKNOWN` rows, which post on the tip with their originating file named). Every other
   PR in the chain gets only a short note pointing at that overview — never its own,
   contradictory verdict. Findings still post inline on the PR the attribution resolved
   to, so each author gets their own comments. In **piecemeal** mode, an MR that fails its
   own build gate is additionally blocked on its own — say which of the two blocked it.

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
