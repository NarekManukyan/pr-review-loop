---
name: review-pr-slack
description: This skill should be used when the user asks to "review MRs and send to Slack", "review-pr-slack", "panel review these merge requests", "review PR and DM the author", provides GitLab MR / GitHub PR URLs asking for a review delivered as an HTML report via Slack instead of inline comments, or provides a Slack message URL containing MR links to review. Runs a 4-agent panel (3 reviewer personas + a build/analyzer check in an isolated worktree), builds a self-contained GitHub-style HTML report (overview + build status + all comments + fix prompts), and after user confirmation sends a short verdicts-only Slack message — as a DM to the PR author, or as a thread reply when a Slack message URL is provided. Never posts comments on GitLab/GitHub.
version: 1.0.0
---

# Review PR → Slack Report

Run a 3-reviewer panel over one or more GitLab MRs (or GitHub PRs), produce a single self-contained GitHub-style HTML report (overview + inline threaded comments + fix prompts), and announce it with a short verdicts-only Slack message — DM to the PR author, or a thread reply when a Slack message URL is given. **Never post any comments, notes, or overviews on GitLab/GitHub** — the report and Slack are the only outputs.

## Hard rules

1. No GitLab/GitHub comments, approvals, or notes — read-only API access.
2. Before sending anything to Slack, show the user the matched Slack person and get explicit confirmation (AskUserQuestion).
3. Skip generated files entirely: `*.g.dart`, `*.freezed.dart`, `*.gen.dart`, `*.tailor.dart`, `*.config.dart`, `*.gr.dart`, `*.chopper.dart`, `*.mocks.dart`, `lib/gen/**`, `lib/src/l10n/**`, `pubspec.lock`, lockfiles, `node_modules`, `dist/`. Extend the list from the repo's CLAUDE.md if present.
4. Read the repo's `CLAUDE.md` first and apply its review standards (FACT vs ASSUMPTION: only provable findings become comments).
5. Findings reference NEW-file line numbers.
6. **All Slack SENDS go through the `slack-send` skill** (`scripts/msg.sh` for the verdict message, `scripts/send.sh` for the HTML upload) — never call the MCP `slack_send_message` to deliver the review. The MCP Slack connector is used **only for READING** (`slack_read_thread`, `slack_search_users`) since the scripts don't read. If the CC App token is missing, the fix is to install it (`~/.claude/skills/slack-send/install.sh`), not to send via MCP — file upload is impossible without it, so silently degrading to an MCP message-with-no-file defeats the skill's purpose.

## PR state reactions (the anchor message)

When the trigger is a **channel message** (a Slack message URL, or watch mode — §Loop below), that message is the **anchor**, and its reactions encode PR state at a glance (managed via `slack-send/scripts/react.sh`, as the reviewer):

| Emoji | Meaning | When |
|---|---|---|
| 👀 `eyes` | review in progress | set at review start (before the panel runs) |
| ✅ `white_check_mark` | approved | on deliver, if every MR verdict is Approve / Approve-with-minor-fixes and no P0/P1 remain |
| 🔧 `wrench` | changes requested | on deliver, if any MR is Request Changes (or a build is broken / merge conflicts / any P0/P1 open) |

`react.sh state <channel> <anchor_ts> <emoji>` clears prior state emojis and sets one, so transitions are clean (👀 → ✅/🔧). Skip reactions for the pure-DM case (no channel anchor message).

## Slack auth errors — prompt, don't dead-end

Any Slack script may fail because the token is missing or under-scoped:
`msg.sh`/`send.sh` exit `3` (`NO_TOKEN`); `watch.sh`/`react.sh` also emit
`SCOPE_ERROR:` on stderr and exit `4` (missing `channels:history` /
`groups:history` / `reactions:*`). **Do not** just print the error and the fix
command — handle it:

- **Interactive run** (manual `/review-pr-slack`, or a watch cycle run by hand):
  use `AskUserQuestion` — "Slack needs (re)connecting to continue (missing
  token/scopes). Reconnect now?" with options **Reconnect now** / **Skip Slack for
  this run** / **Cancel**. On *Reconnect now*, run
  `~/.claude/skills/slack-send/install.sh` (it opens the browser OAuth — the user
  approves the scopes), then retry the failed step. On *Skip*, finish the review
  and hand back the HTML report path without posting.

- **Unattended `/loop`** (no user to ask): report the problem **once** and **stop
  the loop** — do not let it repeat the same failure every cycle. Tell the user to
  re-auth (`slack-send/install.sh`) and re-run `/loop`.

This applies everywhere a Slack call is made (reactions, message, upload, channel
scan), not just at delivery.

## Workflow

### 1. Resolve input & fetch MRs/PRs

Input is either (a) MR/PR URLs directly, or (b) **a Slack message URL** — the preferred form. For a Slack message URL: parse channel + ts (see `references/reviewer-prompts.md` § Slack target resolution), read the message **and every reply in its thread** (`slack_read_thread`), and extract every GitLab MR / GitHub PR URL found anywhere in the thread (also match bare `!<N>` / `#<N>` references when the message names the repo). That same thread automatically becomes the reply target for the verdict message. If no MR URLs can be extracted, show the message text and ask the user which MRs to review.

**Thread replies are review context, not just link sources.** If the thread contains a previous review round (an earlier verdict message from this skill / the user) and developer replies to it, this is a **re-review**: collect every developer reply, map each one to the finding it responds to, and write a `thread-context.md` in the scratchpad (one entry per reply: author, quote, which finding/file it concerns). Pass this file to all reviewer agents. Rules for handling replies are in `references/reviewer-prompts.md` § Developer replies — the short version: verify claims against code (a reply saying "fixed" counts only if the code proves it), honor explicit deferrals with guardrails, respond substantively to disagreements, and never re-assert a finding while ignoring the author's answer.

For GitLab use `glab api` (already authenticated); for GitHub use `gh`.

Per MR: metadata (title, author name+username, source/target branch, state, head SHA, **conflict state** — `has_conflicts` / `merge_status` on GitLab; `mergeable` / `mergeStateStatus` on GitHub), then diffs and full files into the scratchpad:

```bash
glab api "projects/<url-encoded-path>/merge_requests/<N>"          # metadata
glab api "projects/<url-encoded-path>/merge_requests/<N>/diffs?per_page=100"  # diffs
glab api "projects/<path>/repository/files/<url-encoded-file>/raw?ref=<sha>"  # full file at head
```

Write per-MR unified diffs (generated files excluded) to `mr<N>.diff` and full sources to `mr<N>-files/<path>` in a scratchpad working dir. Note stacked MRs (target branch = another MR's source) and already-merged state — report both in the output.

### 1b. Recall review memory

If the target repo is checked out locally (the usual case — the skill is run from inside it; else `git clone` it to reach its `.review-memory/`), recall this repo's past review outcomes before the panel runs:

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py recall <repo-root> --area "<changed features / paths across the MRs>"
```

Pass the output to all reviewer agents as calibration — it is subordinate to CLAUDE.md/ADRs. Honor prior deferrals (Reviewer D / the panel should verify the promised guardrail landed), do **not** re-raise findings the author previously resolved/disputed/clarified unless the code materially changed, and load `.review-memory/rules.md`. This is the persistent counterpart to the per-thread `thread-context.md`: thread replies cover *this* Slack thread; review memory carries outcomes across all prior rounds and MRs for the repo. No `.review-memory/` yet → first round, nothing to recall.

**Mark the anchor in-progress.** If there is a channel anchor message (Slack-URL or watch mode), set 👀 now so the channel shows the PR is being reviewed:

```bash
~/.claude/skills/slack-send/scripts/react.sh state <channel> <anchor_ts> eyes
```

**Carry-forward watch items.** Recall may surface `⚠ CARRY-FORWARD WATCH ITEMS` — human-flagged areas that must be inspected this round (e.g. "complex logic not verified — check in future PRs"). Treat these as must-inspect and report on each in the relevant MR's overview. Conversely, when a **human** (you / the lead) leaves a carry-forward directive in the thread — a comment asking to keep watching some logic in future reviews rather than disputing/resolving a specific finding — record it as a watch item so it persists across future PRs:

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py note <repo-root> \
  --by "<author>" --area "<file/paths>" --title "<short>" --text "<the concern>"
```

### 1c. Detect the stack

Determine the repo's stack from its manifest (`pubspec.yaml` → Flutter/Dart, `package.json` → JS/TS + framework, `go.mod` → Go, `pyproject.toml` → Python, `*.csproj` → .NET…). Use it to fill `<stack>` in the persona prompts and to pick stack-appropriate checks: the three personas keep their lenses (architecture · correctness · performance/quality) but apply the detected stack's idioms + the repo's `CLAUDE.md`/linter — not Flutter's by default. Reviewer D already auto-detects the stack for its compile/analyze step.

### 2. Run the 4-agent panel

Spawn four agents **in parallel** (Agent tool, `run_in_background: true`):

- **A — Architecture & Patterns**: layering, BLoC/state-management correctness, DI, separation of concerns
- **B — Correctness & Edge Cases**: logic bugs, null safety, async/races, error handling, hardcoded placeholders
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

- **C — Performance & Code Quality**: rebuilds, per-frame/per-keystroke work, complexity, naming, localization/design-system violations, dead code
- **D — Build & Analyze**: verifies each open MR actually compiles and passes static analysis. Per MR: fetch the source branch, create an isolated `git worktree` (never touch the user's working tree), install deps and run the stack's compile/analyze step (Flutter: `flutter pub get` + codegen if needed + `dart analyze`; Node: install + `tsc`/build; Go: `go build ./... && go vet`), then remove the worktree. Compile/analyzer **errors** → P0 findings with the tool output quoted; **warning/info counts** → reported per MR for the verdict. Skip already-merged MRs.

Use the prompt templates in `references/reviewer-prompts.md` verbatim, substituting paths and MR context. When `thread-context.md` exists (re-review), include its path in every reviewer prompt with the instructions from § Developer replies. Reviewers A–C return a JSON array of findings `{mr, file, line, severity: P0|P1|P2, reviewer, category, title, body, snippet}` plus one `{mr, reviewer, summary}` per MR; on re-reviews they additionally return reply resolutions `{mr, reviewer, reply_to: "<dev quote>", resolution: "resolved|deferred|disputed|clarified", response: "..."}`. Reviewer D additionally returns per MR: `{mr, reviewer: "D", build: {compiles: bool, analyzer_errors: N, analyzer_warnings: N, analyzer_infos: N, tool: "dart analyze", notes: "..."}}`.

Agents may emit HTML entities (`&amp;`, `&lt;`) — run `html.unescape` on every string field before use.

### 3. Merge & dedupe

Combine the three result sets. When 2–3 reviewers hit the same issue:

- Keep the strongest write-up as the **canonical** finding (highest severity wins; else most detailed).
- Convert the others to short **"+1" replies**: `{...same file/line/severity, title: "+1 — agree", body: "<unique additional facts only>", snippet: "", plusone: true}` — threaded under the canonical in the report. `plusone` entries are excluded from severity counts.
- Align line numbers of duplicates so they thread together.

Write `findings.json` (all entries, sequential `id` field, summaries included) and `meta.json`:

```json
{
  "title": "…", "date": "YYYY-MM-DD", "order": [57, 59, 58],
  "57": {"title": "…", "author": "…", "source": "…", "target": "…",
          "state": "merged|opened", "url": "…",
          "verdict": "✅ Approve | ⚠️ Approve with minor fixes | 🔄 Request Changes",
          "build": {"compiles": true, "analyzer_errors": 0, "analyzer_warnings": 12,
                     "tool": "dart analyze", "notes": ""},
          "conflicts": false,  "merge_status": "can_be_merged",
          "discussion": [{"by": "Davit", "quote": "this is intentional, backend clamps it",
                           "resolution": "deferred",
                           "response": "Accepted as deferred — add a TODO + ticket before merge."}],
          "fix_prompt": "--- FIX PROMPT --- …"}
}
```

On re-reviews, fill `discussion` per MR from the reviewers' reply resolutions (deduped): each entry renders in the report as a "💬 Thread follow-ups" block in that MR's overview. Resolutions: `resolved` (code proves the fix), `deferred` (author said later/out-of-scope — state the guardrail asked for), `disputed` (reviewer still disagrees — state why, cite code), `clarified` (author was right — finding withdrawn, say so plainly).

Set `conflicts` per MR from step 1's fetch (`has_conflicts` / `merge_status` on GitLab, `mergeable`/`mergeStateStatus` on GitHub). The report shows it as a **Conflicts column**.

Verdict policy: **merge conflicts OR** build broken OR any P0/P1 → 🔄 Request Changes; P2-only → ⚠️ Approve with minor fixes; clean → ✅ Approve. **A conflicting MR is never Approve** — its verdict is `🔄 Request Changes — conflicts with <target>` (also add a P1 conflict finding). Append the build result too, e.g. `🔄 Request Changes — build ❌ (2 analyzer errors)`. Already-merged MRs: note "fold into follow-up"; build + conflict checks skipped.

Each MR gets a `fix_prompt`: a self-contained prompt the developer pastes into Claude Code. **Use the full template in `references/reviewer-prompts.md` § Fix-prompt template verbatim** — it forces the fixer to (1) read CLAUDE.md + all ADRs and the surrounding code first, (2) fix the root cause and explicitly forbids cosmetic non-fixes (adding comments, reformatting, suppressing lints, swallowing errors, deleting code/tests), (3) verify with codegen/format/analyze/tests and explain each fix against a rule/ADR. Every finding line must include `file:line` + the required end state, not just the symptom.

### 4. Build the HTML report

Run the bundled generator from the scratchpad dir containing `findings.json`, `meta.json`, and `mr<N>.diff` files:

```bash
python3 ~/.claude/skills/review-pr-slack/scripts/build_html.py
```

Syntax highlighting is baked in at build time via shiki (`scripts/highlight.mjs`, needs `node`; `shiki` is installed in `scripts/node_modules`) so colors survive sandboxed previews like Slack. If node/shiki is unavailable the page falls back to a client-side CDN script automatically — no action needed.

Output: `mr-review.html` — GitHub-style diff view showing **only commented code**: files without findings collapse to a name-only row, and within commented files only hunks containing a comment render (a "… N hunks without comments hidden" marker keeps the omission visible). Comments thread inline at their lines; comments outside changed hunks render in a per-file tail section. Per-MR overview includes severity counts, reviewer summaries, verdict, and a collapsible fix prompt. Copy the file to `~/Desktop/mr-review-<Ns>.html`.

### 5. Resolve the Slack target & confirm

The HTML report is the single review artifact (it contains the overview table, all findings, and fix prompts) — the Slack message carries **verdicts only**. Do not create a Slack canvas.

Target resolution:

- **Slack message URL provided** (in the original request or during confirmation) — reply in that message's thread. Parse `https://<ws>.slack.com/archives/<CHANNEL_ID>/p<digits>` → `channel_id = CHANNEL_ID`, `thread_ts = digits[:-6] + '.' + digits[-6:]`. If the URL has `?thread_ts=<ts>` query param, use that value instead (the `p<digits>` part is then the reply, not the parent). These become `msg.sh`'s `TARGET` (channel id) + `thread_ts` in step 6.
- **Otherwise** — DM the MR author: resolve their user ID (`slack_search_users` by display name, or let `msg.sh` resolve `@Display Name` directly; fall back to username/email). That user ID is the `TARGET`.

Then **stop and confirm** via AskUserQuestion, showing the resolved target (person: name, Slack ID, email, title — or channel + thread parent). Offer:

1. **Send verdict message** (to the resolved target)
2. **Don't send yet**

### 6. Deliver

Delivery goes through the **`slack-send`** skill so both the verdict message and the report post **as the reviewer** (their CC App user token), and the report lands in the same thread — no manual drag.

Compose one short message (template in `references/reviewer-prompts.md` § Verdict message): greeting, totals line (`P0/P1/P2`), one bullet per MR — link + verdict (build ✅/❌ + warning count) + bolded P0/P1 headlines only — and a closing line that the full review is in the attached HTML report. On re-reviews add: `Addressed your replies: ✅ n resolved · 📌 n deferred · ❌ n still open — details in the report.`

**Step 6a — post the verdict message** (as the reviewer):

```bash
~/.claude/skills/slack-send/scripts/msg.sh "<TARGET>" "<verdict message text>" "<thread_ts?>"
```

- `TARGET`: DM the author → their user ID or `@Display Name` (msg.sh resolves names); thread-reply case → the channel ID.
- `thread_ts`: for the Slack-URL case, the parent thread ts (so the verdict is a reply); for a fresh DM, omit.
- Capture the `ts=<...>` that `msg.sh` prints — that's the parent for the report upload.
- **No CC token?** `msg.sh` exits `3`. Do **not** silently send via MCP. Stop and tell the user to run `~/.claude/skills/slack-send/install.sh` once (connects the CC App → posts as them and unlocks the report upload), then retry. Only if the user explicitly declines the install, fall back to the MCP connector for the verdict message alone (posts under the connector identity, **no file upload possible**) — and make that limitation explicit to the user.

**Step 6b — upload the HTML report into that thread:**

```bash
~/.claude/skills/slack-send/scripts/send.sh \
  "<Desktop path to mr-review-<Ns>.html>" \
  "<TARGET (channel ID for thread; user ID for DM)>" \
  "📄 Full review report" \
  "<ts from 6a>"
```

- On `NO_TOKEN`/token error: the MCP connector **cannot upload files**, so there is no auto-fallback — tell the user to either run `~/.claude/skills/slack-send/install.sh` (connect the CC App) and retry, or drag `mr-review.html` into the thread manually. Surface the error.
- On any other `ERROR: ...`: report it and fall back to the manual-drag reminder.

Report the verdict message link back to the user.

**Step 6c — set the verdict reaction** (channel anchor only): swap 👀 for the outcome emoji so the channel reflects PR state:

```bash
# emoji = white_check_mark if all approved & no P0/P1 & no conflicts; else wrench
~/.claude/skills/slack-send/scripts/react.sh state <channel> <anchor_ts> <emoji>
```

### 7. Record review memory

After the verdict is sent, persist this round's outcomes so future reviews of the repo are calibrated. Build `decisions.json` from `findings.json` + `meta.json`:

- One entry per **canonical** finding (skip `plusone` "+1" replies). Map: `mr`, `file`, `line`, `category`, `severity`, `title` directly; `reviewer` = the finding's reviewer letter; `round` = this review round.
- `dev_resolution`: `open` on round 1; on re-reviews, take it from that MR's `discussion` resolutions in `meta.json` (`resolved | deferred | disputed | clarified`) matched to the finding; `rationale` = the developer's quote / your response.
- Top level: `stack` (detected, e.g. `flutter-bloc`), `commit` (each MR's head SHA — or set per-entry if they differ), `date` (today).
- **Omit `signature`** — it auto-derives from file+title+category and links the same finding across rounds.

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py record <repo-root> --input <scratchpad>/decisions.json
```

`.review-memory/` is committed to the repo, so this is a normal change the team reviews via PR. If the repo was only cloned transiently (not the user's working checkout), tell the user the memory update lives in that clone and offer to open a PR with it rather than leaving it stranded. Recurring confirmed lessons get promoted by a human into CLAUDE.md/an ADR via `memory.py distill`.

## Loop / watch mode

The skill can run continuously over a channel, driven entirely by **reactions as
state** (no external DB): unreacted PR message = to-do, 👀 = in progress, ✅/🔧 =
done. Wrap one poll cycle in the `/loop` skill:

```
/loop 10m /review-pr-slack-watch #<channel>
```

Each cycle (`commands/review-pr-slack-watch.md`):

1. `slack-send/scripts/watch.sh <channel>` → JSON of every top-level message
   containing an MR/PR URL, with its `state` (new / in_progress / reviewed),
   reply count, and last-reply ts.
2. **New PR** (`state == "new"`) → run the full workflow above on that message's
   URLs, replying the verdict in its thread. `eyes` at start → `white_check_mark`
   /`wrench` at the end.
3. **Next round** (`state == "reviewed"` AND `last_reply_ts` is newer than the
   verdict, from the PR author) → `slack_read_thread` to confirm the author is
   asking for a re-review / says it's ready. If yes, re-run as a re-review round
   (thread replies become `thread-context.md`, memory recall applies): `eyes`
   again → new verdict emoji. If the reply is just discussion, skip.
4. `state == "in_progress"` → already being handled; skip (unless clearly stale).
5. Nothing actionable → exit quietly. Never touch messages without PR URLs.

Guardrails for unattended runs: in loop mode, skip the interactive
send-confirmation (the `/loop` invocation is the standing authorization) but keep
every other hard rule — no GitLab/GitHub comments, generated-file skipping,
FACT-vs-ASSUMPTION. Cap work per cycle (e.g. ≤3 PRs) so one cycle can't run away;
the next cycle picks up the rest.

## Interactive report (developer replies → next round)

The HTML report is interactive when opened in a browser (Slack's preview is
read-only — download to interact). Each comment has a stable `#id`, a status
(fixed / disagree / later) and a reply box; each file has a "viewed" checkbox that
collapses it; state persists in `localStorage`. A **Copy Next Round** button
assembles every comment the developer responded to into Slack-ready text:

```
Next round — <title>
• <file:line> — <finding title> [fixed|disagree|later]
    ↳ <their reply>
```

The developer pastes that into the PR's Slack thread. On the **next review round**
this is exactly the thread text the skill reads as `thread-context.md`, and the
status tags map to memory resolutions: `fixed → resolved`, `disagree → disputed`,
`later → deferred`. So a dev answering findings in the report, one click, feeds
straight back into the re-review and review memory — no hand-writing.

When delivering, tell the developer: open the report, answer the comments, hit
**Copy Next Round**, paste into the thread to trigger round N+1.

## Final output to the user

Lead with results: totals, per-MR verdict + headline findings, the sent Slack message link, HTML path on Desktop, and confirmation that the report was auto-uploaded into the thread (or, if the upload failed / token missing, the reminder to attach it manually).

## Additional Resources

- **`references/reviewer-prompts.md`** — the three persona prompt templates, merge/dedupe rules, Slack target resolution & verdict-message template
- **`scripts/build_html.py`** — GitHub-style HTML report generator (reads `findings.json`, `meta.json`, `mr<N>.diff` from CWD)
- **`slack-send` skill** (`~/.claude/skills/slack-send/`) — the **required** delivery path for step 6: `scripts/msg.sh` posts the verdict message and `scripts/send.sh` uploads the HTML report into the thread, both as the reviewer. Needs a Slack user token in `~/.slack-upload-token`; see that skill's `README.md` / `install.sh`. The Slack MCP connector is read-only in this workflow (thread/user lookups) and is a message-only last resort **only** if the user declines installing the token.
- **`review-memory` skill** (`~/.claude/skills/review-memory/`) — per-repo learning layer. Step 1b `recall` and step 7 `record` go through `scripts/memory.py`. Calibrates reviews from past outcomes + developer responses; never overrides CLAUDE.md/ADRs.
