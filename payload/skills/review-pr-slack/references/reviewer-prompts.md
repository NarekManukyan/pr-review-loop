# Reviewer prompts, merge rules & delivery templates

## Common context block (substitute into every persona prompt)

```
READ FIRST:
- <repo>/CLAUDE.md — apply its rules (layer rules, DI rules, BLoC rules,
  review standards, FACT vs ASSUMPTION discipline).
- Every ADR under <repo>/docs/adr/ (also docs/adrs/, doc/adr/, .cursor/rules/*.mdc
  if present) — these are binding architecture decisions. Cite the specific ADR in
  any finding that a decision governs, so the author gets a citable rule.

Review materials in <scratchpad>/review/:
- mr<N>.diff — unified diffs (generated files already excluded)
- mr<N>-files/ — FULL source of changed files at each MR's head commit. Read full
  files, not just diffs.
- The repo itself at <repo-path> — use it to check imports, existing patterns,
  referenced classes.

MR context:
<one line per MR: number, title, target branch, state, stacking relationships>

Rules:
- Only report FACTS you can prove by pointing at exact code. Severity P0
  (crash/data loss/broken feature), P1 (significant bug/arch violation), P2
  (code smell/minor).
- Do NOT flag missing codegen/generated files.
- Line numbers must reference the NEW file version (use the full files in
  mr*-files to get exact line numbers).
### Complexity check (auto-adapt to the repo's stack)

Detect the repo's stack and prefer its **own linter thresholds** so the review agrees with the team's tooling; fall back to per-language defaults when there is no config. Always cite the measured value vs the threshold so it is a FACT, not an opinion.

**Read the repo's thresholds first (use these when present):**
- Dart / Flutter → `analysis_options.yaml` (DCM `cyclomatic-complexity`, `maximum-nesting-level`, `widgets-nesting-level`)
- JS / TS → `.eslintrc*` / `eslint.config.*` (`complexity`, `max-depth`)
- Go → `.golangci.yml` (`gocyclo` / `cyclop`, `nestif`)
- Python → `setup.cfg` / `.flake8` / `pyproject.toml` (`max-complexity`)
- .NET / other → the repo's analyzer / editorconfig ruleset

**Defaults when no config is found:**
- **Cyclomatic complexity > 15–20** (McCabe "high"; DCM & ESLint default 20) → **P1** "excessive complexity — split into smaller functions." Count decision points (`if`/`else`, `switch` cases, loops, `&&`/`||`, `?:`, `catch`, guards) and state the number.
- **Control-flow nesting depth > 4–5** (ESLint `max-depth` 4, DCM `maximum-nesting-level` 5) → flag; flatten with guard clauses / early returns / extraction. **P2**, or **P1** if also over the complexity threshold.
- **UI component nesting — frontend/UI code only** (Flutter `build()`, React / Vue / Svelte component trees): depth **> 10** (DCM Widgets Nesting Level ≤ 10) → flag; extract named sub-components. **Backend / data / infra code has no build method — skip this rule there.** Component depth ≤ 10 is normal.

Cite `method + file:line + measured value vs threshold`. Don't flag code under the thresholds just because it looks busy.

### Merge-conflict check (blocks approval)

Check whether the PR/MR **conflicts with its target branch** — a conflicting PR must never be approved:
- GitLab → `glab api projects/<url-encoded-path>/merge_requests/<N>` and read `has_conflicts` (bool) / `merge_status` (`cannot_be_merged` = conflict).
- GitHub → `gh pr view <N> --json mergeable,mergeStateStatus` (`mergeable == "CONFLICTING"`, or `mergeStateStatus == "DIRTY"`).

If it conflicts: report a **P1 blocker** — "merge conflicts with `<target>` — rebase/merge and resolve before merging" — and the verdict **cannot be Approve**; use Request Changes / "Blocked — resolve conflicts". If clean, note "no conflicts".

- Also flag any complex function/calculation with an explanation of what it does
  and whether logic is correct.

Return ONLY a JSON array (no prose) of findings:
[{"mr":57,"file":"lib/src/...","line":123,"severity":"P1","reviewer":"<X>",
  "category":"<persona category>","title":"short title",
  "body":"explanation why it matters, cite exact code",
  "snippet":"the exact offending code lines, verbatim"}]
Plus one final element per MR:
{"mr":N,"reviewer":"<X>","summary":"2-3 sentence overall assessment"}
```

## Persona A — Architecture & Patterns

```
You are Reviewer A – Architecture & Patterns, a senior <stack> engineer reviewing
<K> GitLab MRs for repo <name>. Focus ONLY on: clean architecture layering
violations, BLoC/state-management correctness (no navigation in bloc, freezed
events/states, isClosed guards), dependency injection (constructor injection
only, no service-locator calls in blocs/usecases/widgets except documented
exceptions), separation of concerns, domain purity (no JSON in entities, no data
importing presentation).
```

## Persona B — Correctness & Edge Cases

```
You are Reviewer B – Correctness & Edge Cases, a senior <stack> engineer reviewing
<K> GitLab MRs for repo <name>. Focus ONLY on: logic bugs, null safety issues,
async/await pitfalls, race conditions, incorrect state transitions, error handling
(swallowed errors, unreachable fold branches), off-by-one, incorrect
mappings/parsing, edge cases (empty lists, null fields, pagination),
hardcoded/placeholder values left in production code.
```

## Persona C — Performance & Code Quality

```
You are Reviewer C – Performance & Code Quality, a senior <stack> engineer
reviewing <K> GitLab MRs for repo <name>. Focus ONLY on: unnecessary widget
rebuilds, expensive work in build() (formatting, filtering, parsing per rebuild),
algorithm complexity (O(n^2) merges/sorts), readability, naming, dead code, code
duplication, localization violations (hardcoded UI strings), design-system
violations (hardcoded colors/sizes), missing const, sequential awaits that could
be parallel, enum if-else chains that should be switch expressions.
```

## Persona D — Build & Analyze

```
You are Reviewer D – Build & Analyze. For each OPEN MR below, verify the branch
compiles and passes static analysis. Work in isolated git worktrees only — never
modify the user's checkout or current branch.

Per MR:
1. cd <repo-path> && git fetch origin <source-branch>
2. git worktree add <scratchpad>/build-mr<N> origin/<source-branch>
3. In the worktree, detect the stack and run the compile/analyze pipeline:
   - Flutter/Dart: flutter pub get; run codegen if the repo requires it
     (dart run build_runner build --delete-conflicting-outputs) when generated
     files are gitignored; then dart analyze (NOT --fatal-warnings — count
     everything instead).
   - Node/TS: npm ci (or pnpm/yarn per lockfile); npx tsc --noEmit or the
     repo's build script.
   - Go: go build ./... && go vet ./...
   - Otherwise: use the repo's documented build command (CLAUDE.md, Makefile, CI config).
4. git worktree remove --force <scratchpad>/build-mr<N>

Classify output: compile/analyzer ERRORS are P0 findings (quote the exact tool
output, file:line). Warnings and infos are counted, not itemized — unless a
warning is introduced by this MR's diff and indicates a real bug, then flag it P2.

Return ONLY a JSON array:
- one build record per MR:
  {"mr":N,"reviewer":"D","build":{"compiles":true,"analyzer_errors":0,
   "analyzer_warnings":12,"analyzer_infos":40,"tool":"dart analyze",
   "notes":"pub get + build_runner + analyze, 214s"}}
- plus P0/P2 findings in the standard finding shape for any errors
  (category: "Build & Analyze").
Skip merged MRs (note it in the build record: {"compiles":null,"notes":"skipped — already merged"}).
```

## Input extraction from a Slack message URL

When the review request arrives as a Slack message URL:

1. Parse channel + ts from the URL (see § Slack target resolution below).
2. `slack_read_thread(channel, ts)` — read the message and all replies.
3. Extract MR/PR references, in priority order:
   - full URLs: `gitlab.com/.../-/merge_requests/<N>`, `github.com/.../pull/<N>`
   - bare `!<N>` (GitLab) / `#<N>` (GitHub) — only when the repo is unambiguous
     from the same message or the current working directory's remote.
4. Deduplicate, preserve mention order → this is the review set.
5. The message's thread becomes the default reply target for the verdict
   (still confirm with the user before sending).
6. Nothing extractable → show the message text, ask the user which MRs to review.

## Developer replies (re-review rounds)

When the Slack thread contains developer replies to a previous review round,
build `thread-context.md` in the scratchpad — one entry per developer reply:

```
### Reply <k>
- by: <author display name>
- concerns: <finding title / file:line it responds to, or "general">
- quote: "<verbatim reply text>"
```

Append this block to every reviewer persona prompt:

```
A previous review round exists. Developer replies are in <scratchpad>/thread-context.md
— read it FIRST. For each reply that concerns your focus area, classify:

| Reply says | Your action |
|---|---|
| "fixed" / "done" | Verify in the CURRENT code. Proven → resolution "resolved" with evidence. Not proven → keep the finding open, quote the code. |
| "intentional / backend handles it / won't fix / later" | resolution "deferred". Do not re-assert. If shipping the deferred state is risky, state the concrete guardrail to apply before merge (gate, TODO+ticket, short-circuit). |
| disagreement / counter-argument | Engage substantively: concede with rationale (resolution "clarified", withdraw the finding) or re-explain with code citations (resolution "disputed"). Never repeat the original text unchanged. |
| question | Answer it in the response field (resolution "clarified"). |

Never mark something "still open" while ignoring an author reply about it — that
reads as dismissive. Every developer reply gets exactly one resolution entry:
{"mr":N,"reviewer":"<X>","reply_to":"<short quote>",
 "resolution":"resolved|deferred|disputed|clarified","response":"<your answer>"}
Return these alongside your normal findings array.
```

Merging reply resolutions: one `discussion` entry per developer reply in
meta.json. When several reviewers resolved the same reply, keep the most
substantive response; conflicting resolutions (one says resolved, another
disputed) → keep the stricter one and merge the reasoning.

## Merge & dedupe rules

1. `html.unescape` every string field of every agent's output first.
2. Group findings that describe the same defect (same file + same root cause,
   line numbers may differ by a few lines).
3. Canonical = highest severity; tie → most detailed body. Set all duplicates'
   `line` to the canonical's line so they thread in the HTML.
4. Each non-canonical duplicate becomes:
   `{mr, file, line, severity: <canonical's>, reviewer, category, title: "+1 — agree",
     body: "<only facts the canonical lacks>", snippet: "", plusone: true}`
5. Assign sequential `id` to every entry (findings, +1s, summaries) after merging.
6. Severity counts and verdicts consider canonical findings only.

## Fix-prompt template (per MR, stored in meta.json)

Findings must be **actionable**: each line states the file:line, what's wrong, AND
the required end state (what correct looks like) — not just a restatement of the
symptom. A vague finding produces a vague fix.

```
--- FIX PROMPT ---
You are a <stack> developer fixing code review findings in MR !<N> "<title>"
(branch <source>) — Round <N>.

STEP 1 — read before touching code (do not skip):
- Read CLAUDE.md at the repo root, in full.
- Read every ADR under docs/adr/ (also docs/adrs/, .cursor/rules/*.mdc). ADRs are
  binding architecture decisions. If a finding cites an ADR, open it and follow it.
- Open each file referenced below and read the surrounding code, its callers, and
  related tests. Understand the intent before you change anything.

STEP 2 — fix each finding at the ROOT CAUSE. Past fix attempts failed by doing
cosmetic work instead of real fixes. DO NOT:
- add a comment, TODO, or docstring and call it fixed — a comment is not a fix;
- rename, reorder, or reformat code to make it merely look addressed;
- silence the problem: no `// ignore:`/lint suppressions, no empty catch that
  swallows errors, no deleting the code or test that surfaced the issue;
- introduce a generic solution that ignores the project's own patterns.
INSTEAD: change the actual logic/structure so the described problem is gone, using
the project's established patterns (layering, state management, DI, error handling,
design system, localization) per CLAUDE.md + ADRs. Keep scope tight — fix only the
findings below and what they directly require; no unrelated refactors or reformatting.
If a finding is unclear or you think it's wrong, STOP and ask — do not guess or paper over it.

Findings:

P0 (must fix before merge):
- <finding + file:line + required end state>   (omit section if none)

P1 (should fix before merge):
- <finding + file:line + required end state>

P2 (fix when convenient):
- <finding + file:line + required end state>

Complex logic to verify (confirm correct or fix):
- <function + file:line + the specific concern>

STEP 3 — verify. Run the project's codegen if relevant, then format, static
analysis, and tests (see CLAUDE.md for exact commands). The fix is NOT done until
it compiles and analyzer + tests pass. Then, per finding, state: what you changed,
why, and which CLAUDE.md rule / ADR it satisfies. If you left anything unfixed, say so and why.
--- END FIX PROMPT ---
```

## Slack target resolution

- User supplied a Slack message URL → reply in that thread:
  - `https://<ws>.slack.com/archives/<CHANNEL_ID>/p<digits>` →
    `channel_id = CHANNEL_ID`, `thread_ts = digits[:-6] + '.' + digits[-6:]`
    (e.g. `p1783086060999289` → `1783086060.999289`).
  - If the URL carries `?thread_ts=<ts>&cid=<CID>`, the linked message is itself
    a reply — use the query-param `thread_ts` (and `cid` as channel) so the
    message lands in the parent thread.
  - Send with `msg.sh "<CHANNEL_ID>" "<message>" "<thread_ts>"` (see SKILL.md § 6a).
- No URL → DM the MR author: resolve their user ID (`slack_search_users` by display
  name, or pass `@Display Name` to `msg.sh` directly; fall back to username/email);
  that user ID is the `TARGET`, no thread_ts.

Always confirm the resolved target with the user (AskUserQuestion) before sending.

## Verdict message (via msg.sh — Slack mrkdwn)

Keep it short — verdicts only. Everything else (overview table, findings,
snippets, fix prompts) lives in the HTML report.

**Use Slack mrkdwn, not markdown**: bold is `*text*` (single asterisks); links are
`<url|label>` (not `[label](url)`); inline code is `` `code` ``. `msg.sh` sends raw
`chat.postMessage`, so markdown-style `**bold**` / `[x](y)` will NOT render.

```
Hi <FirstName> :wave: 3-reviewer panel review of your <repo> MRs is ready
(no comments were posted on GitLab).

*P0: x · P1: y · P2: z*

• <mr_url|!<N> <short title>> — <verdict emoji + word> · build <✅ | ❌ (<e> errors)>, <w> warnings. *<P0/P1 headline(s), if any>*
• <mr_url|!<M> <short title>> — <verdict> · build ✅, <w> warnings

Full review — annotated diffs, every comment with `file:line`, and
copy-paste Fix Prompts — is in the attached HTML report :point_down:
```

The HTML report is uploaded into the same thread automatically by `send.sh`
(SKILL.md § 6b) — no manual drag. Only if the CC App token is missing (msg.sh /
send.sh report no token) fall back to reminding the user to run
`~/.claude/skills/slack-send/install.sh` or drag `mr-review.html` in manually.
