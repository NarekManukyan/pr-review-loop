# Delivery templates & prompt scaffolding (review-pr-slack)

The **review brain is the shared `review-core` engine** — personas, universal lenses
(U1–U12), stack lens packs, and Reviewer D's CI-parity/reachability logic all live in
`~/.claude/skills/review-core/`. This file holds only what is **specific to the Slack
delivery path**: the common context block wrapper, Slack target resolution, developer-
reply handling, merge/dedupe rules, the fix-prompt template, and the verdict message.

> Do not restate persona bodies or stack rules here. Load them from
> `review-core/references/personas.md` + the `lenses/*.md` the resolver
> (`review-core/references/resolver.md`) selects for the repo.

## Common context block (substitute into every persona prompt)

```
YOU ARE PART OF THE review-core PANEL. Read first, in this order:
- ~/.claude/skills/review-core/references/personas.md — your persona (A/B/C/D).
- ~/.claude/skills/review-core/references/universal-lenses.md — U1–U12, always apply.
- The stack lens pack(s) the resolver loaded for this repo:
  <list, e.g. _base-flutter.md + flutter-mobx.md  |  go-postgres.md  |  nestjs.md  |  (none → universal-only)>
- <repo>/CLAUDE.md and every ADR (docs/adr/, docs/adrs/, .cursor/rules/*.mdc) — binding;
  cite the specific ADR in any finding it governs. Repo rules OUTRANK the generic pack.

Review materials in <scratchpad>/review/:
- mr<N>.diff — unified diffs (generated files already excluded per the pack's skip list)
- mr<N>-files/ — FULL source of changed files at each MR's head commit. Read full files.
- The repo at <repo-path> — for imports, existing patterns, referenced classes.

MR context: <one line per MR: number, title, target branch, state, stacking relationships>

Rules:
- Only report FACTS provable by pointing at exact code. Verify claims at HEAD, never from
  resolved=true / stale merge_status (universal lens U9).
- **Findings are NOT limited to changed files.** Unchanged code whose contract or risk
  THIS diff changes is in scope — the composition root (does the new background task get
  drained like its siblings? U14), the siblings (does the new endpoint match its
  neighbors' headers/auth/error mapping? U13), and the consumer on the far side of an
  event (what do they dedup on? U3). The panel's known failure mode is anchoring on
  changed lines: review the blast radius, not just the diff.
- Severity: P0 crash/data-loss/security/broken feature · P1 significant bug/arch
  violation/serious perf · P2 smell/minor.
- Complexity findings cite the measured value vs the repo's linter threshold (U11).
- A PR conflicting with its target (verify via git merge-tree, not just the API flag) is a
  P1 blocker, never Approve (U9).
- Do NOT flag missing codegen/generated files.
- Line numbers reference the NEW file version (use mr*-files for exact numbers).
- Also flag any complex function/calculation: what it does + whether the logic is correct.

Return ONLY a JSON array (no prose) of findings:
[{"mr":57,"file":"...","line":123,"severity":"P1","reviewer":"<A|B|C|D>",
  "category":"<persona category>","title":"short title",
  "body":"why it matters, cite exact code + the rule/ADR/lens","snippet":"the exact offending lines"}]
Plus one final element per MR: {"mr":N,"reviewer":"<X>","summary":"2-3 sentence assessment"}
Reviewer D additionally returns the build record shape from personas.md.
```

The delivery skill fills `<list>` from the resolver output and substitutes the repo/MR
paths. On re-reviews it also appends the `thread-context.md` block (see § Developer
replies).

## Input extraction from a Slack message URL

When the review request arrives as a Slack message URL:
1. Parse channel + ts (see § Slack target resolution).
2. `slack_read_thread(channel, ts)` — read the message and all replies.
3. Extract MR/PR references, priority order: full URLs
   (`gitlab.com/.../-/merge_requests/<N>`, `github.com/.../pull/<N>`), then bare
   `!<N>`/`#<N>` when the repo is unambiguous.
4. Dedupe, preserve mention order → the review set.
5. The message's thread becomes the default reply target for the verdict.
6. Nothing extractable → show the message text, ask which MRs to review.

## Developer replies (re-review rounds)

When the Slack thread contains developer replies to a previous round, build
`thread-context.md` in the scratchpad — one entry per reply:
```
### Reply <k>
- by: <author display name>
- concerns: <finding title / file:line it responds to, or "general">
- quote: "<verbatim reply text>"
```

Append this to every persona prompt:
```
A previous round exists. Read <scratchpad>/thread-context.md FIRST. For each reply in
your focus area, classify (verify against code at HEAD — U9):
| Reply says | Action |
| "fixed"/"done" | Verify in CURRENT code. Proven → resolution "resolved" + evidence. Not proven → keep open, quote the code. |
| "intentional/backend handles it/won't fix/later" | resolution "deferred". Don't re-assert. If shipping it is risky, state the concrete guardrail (gate, TODO+ticket, short-circuit). |
| disagreement | Engage: concede ("clarified", withdraw) or re-explain with code citations ("disputed"). Never repeat the original text unchanged. |
| question | Answer it ("clarified"). |
Never mark "still open" while ignoring an author reply. One resolution per reply:
{"mr":N,"reviewer":"<X>","reply_to":"<short quote>","resolution":"resolved|deferred|disputed|clarified","response":"<answer>"}
Return these alongside the findings array.
```

Merging: one `discussion` entry per reply in meta.json; keep the most substantive
response; conflicting resolutions → keep the stricter one and merge the reasoning.

## Merge & dedupe rules
1. `html.unescape` every string field of every agent's output first.
2. Group findings describing the same defect (same file + root cause; lines may differ).
3. Canonical = highest severity; tie → most detailed body. Set duplicates' `line` to the
   canonical's so they thread.
4. Each non-canonical duplicate becomes
   `{mr,file,line,severity:<canonical's>,reviewer,category,title:"+1 — agree",body:"<only new facts>",snippet:"",plusone:true}`.
5. Assign sequential `id` to every entry after merging.
6. Severity counts / verdicts consider canonical findings only.

## Fix-prompt template (per MR, stored in meta.json)

Findings must be actionable: each line = `file:line` + what's wrong + the required end
state, not just the symptom.
```
--- FIX PROMPT ---
You are a <stack> developer fixing code review findings in MR !<N> "<title>"
(branch <source>) — Round <N>.

STEP 1 — read before touching code: CLAUDE.md (full) + every ADR (docs/adr/, docs/adrs/,
.cursor/rules/*.mdc). Open each referenced file, its callers, and related tests.
Understand intent before changing anything.

STEP 2 — fix each finding at the ROOT CAUSE. Past fix attempts failed by doing cosmetic
work. DO NOT: add a comment/TODO and call it fixed; rename/reorder/reformat to look
addressed; silence it (`// ignore:`/lint suppressions, empty catch that swallows,
deleting the code/test that surfaced it); introduce a generic solution ignoring the
project's patterns. INSTEAD change the actual logic/structure using the project's
established patterns (layering, state management, DI, error handling, design system,
localization) per CLAUDE.md + ADRs + the repo's stack conventions. Keep scope tight —
only these findings. If a finding is unclear or you think it's wrong, STOP and ask.

Findings:
P0 (must fix before merge):
- <finding + file:line + required end state>   (omit section if none)
P1 (should fix before merge):
- <finding + file:line + required end state>
P2 (fix when convenient):
- <finding + file:line + required end state>
Complex logic to verify (confirm correct or fix):
- <function + file:line + the specific concern>

STEP 3 — verify with the repo's REAL CI commands (formatter/linter/analyzer/tests, incl.
build tags — see the stack pack's CI gates). Not done until it compiles and the pipeline's
checks pass. Per finding, state what changed, why, and which CLAUDE.md rule / ADR / lens it
satisfies. If anything is left unfixed, say so and why.
--- END FIX PROMPT ---
```

## Slack target resolution
- User supplied a Slack message URL → reply in that thread:
  - `https://<ws>.slack.com/archives/<CHANNEL_ID>/p<digits>` →
    `channel_id = CHANNEL_ID`, `thread_ts = digits[:-6] + '.' + digits[-6:]`
    (e.g. `p1783086060999289` → `1783086060.999289`).
  - If the URL carries `?thread_ts=<ts>&cid=<CID>`, the linked message is itself a reply —
    use the query-param `thread_ts` (and `cid` as channel).
  - Send with `msg.sh "<CHANNEL_ID>" "<message>" "<thread_ts>"` (SKILL.md § 6a).
- No URL → DM the MR author: resolve their user ID (`slack_search_users` by display name,
  or pass `@Display Name` to `msg.sh`; fall back to username/email); no thread_ts.

Always confirm the resolved target with the user (AskUserQuestion) before sending.

## Verdict message (via msg.sh — Slack mrkdwn)

Short — verdicts only; everything else lives in the HTML report. Slack mrkdwn: bold is
`*text*`, links are `<url|label>`, inline code is `` `code` `` (markdown `**bold**` /
`[x](y)` will NOT render).
```
Hi <FirstName> :wave: 4-reviewer panel review of your <repo> MRs is ready
(no comments were posted on GitLab).

*P0: x · P1: y · P2: z*

• <mr_url|!<N> <short title>> — <verdict emoji + word> · reviewed at `<short_head_sha>` · build <✅ | ❌ (<e> errors)>, <w> warnings. *<P0/P1 headline(s), if any>*
• <mr_url|!<M> <short title>> — <verdict> · reviewed at `<short_head_sha>` · build ✅, <w> warnings

Full review — annotated diffs, every comment with `file:line`, and copy-paste Fix
Prompts — is in the attached HTML report :point_down:
```

Every bullet states **which snapshot the verdict describes** (`reviewed at <short head
sha>`) — a verdict without a SHA is unreconcilable once the branch moves. If
`snapshot_moved` is true for an MR (head moved, or the target advanced between fetch and
delivery — re-checked with `git merge-tree` at delivery, SKILL.md § 3), add a line rather
than reporting a stale result:
`⚠️ Reviewed at \`<short_sha>\`; \`<target>\` has advanced since — re-check conflicts before merging.`
On re-reviews add: `Addressed your replies: ✅ n resolved · 📌 n deferred · ❌ n still open — details in the report.`
The HTML report is uploaded into the same thread automatically by `send.sh` (SKILL.md § 6b).
