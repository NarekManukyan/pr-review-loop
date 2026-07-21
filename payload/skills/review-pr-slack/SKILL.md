---
name: review-pr-slack
description: This skill should be used when the user asks to "review MRs and send to Slack", "review-pr-slack", "panel review these merge requests", "review PR and DM the author", provides GitLab MR / GitHub PR URLs asking for a review delivered as an HTML report via Slack instead of inline comments, or provides a Slack message URL containing MR links to review. Runs a 5-agent panel (architecture / correctness / perf-quality personas + a build-and-CI check in an isolated worktree + a seams-and-blast-radius reviewer), builds a self-contained GitHub-style HTML report (overview + build status + all comments + fix prompts), and after user confirmation sends a short verdicts-only Slack message — as a DM to the PR author, or as a thread reply when a Slack message URL is provided. Never posts comments on GitLab/GitHub.
version: 1.0.0
---

# Review PR → Slack Report

Run a 5-reviewer panel over one or more GitLab MRs (or GitHub PRs), produce a single self-contained GitHub-style HTML report (overview + inline threaded comments + fix prompts), and announce it with a short verdicts-only Slack message — DM to the PR author, or a thread reply when a Slack message URL is given. **Never post any comments, notes, or overviews on GitLab/GitHub** — the report and Slack are the only outputs.

## Hard rules

1. No GitLab/GitHub comments, approvals, or notes — read-only API access.
2. Before sending anything to Slack, show the user the matched Slack person and get explicit confirmation (AskUserQuestion).
3. **Skip generated files entirely — from the diff AND from any read.** The list is
   **stack-specific: use the loaded lens pack's "Generated / skip" section** (this
   baseline is Flutter's; a Go repo's is in `go-postgres.md`, etc.), plus anything the
   repo's CLAUDE.md/.gitignore adds. Baseline: `*.g.dart`, `*.freezed.dart`, `*.gen.dart`,
   `*.tailor.dart`, `*.config.dart`, `*.gr.dart`, `*.chopper.dart`, `*.mocks.dart`,
   `lib/gen/**`, `lib/src/l10n/**`, `pubspec.lock`, lockfiles, `node_modules`, `dist/`.
   **This is the single cheapest token win and it costs zero findings** — measured on
   explorer-back!71, generated files nobody reviews were **68% of the source fetched and
   29% of the diff** (64k of swagger output + 30k of sqlc `models.go`), because the skip
   list was Flutter-shaped and the Go pack's gaps went unapplied. Get this right before
   optimising anything else.
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

Per MR: metadata (title, author name+username, source/target branch, state, head SHA, **conflict state** — `has_conflicts` / `merge_status` on GitLab; `mergeable` / `mergeStateStatus` on GitHub), then the diff into the scratchpad:

```bash
glab api "projects/<url-encoded-path>/merge_requests/<N>"          # metadata
glab api "projects/<url-encoded-path>/merge_requests/<N>/diffs?per_page=100"  # diffs
glab api "projects/<path>/repository/files/<url-encoded-file>/raw?ref=<sha>"  # full file at head
```

Write per-MR unified diffs (generated files excluded — see hard rule 3) to `mr<N>.diff`
and full sources to `mr<N>-files/<path>` in a scratchpad working dir. Note stacked MRs
(target branch = another MR's source) and already-merged state — report both.

**Reviewers must read what their lenses require.** The reads that matter are mandatory,
not optional (`review-core/references/personas.md` § "Reading the code"): the whole file
for a design-system/i18n/dead-code sweep, the whole function for a complexity metric, the
sibling for U13, the composition root's startup *and* shutdown for U5/U14. Findings are
**not limited to changed files** — on `booking-back!31` three of four missed defects lived
in files that were never in the diff.

> **Token note.** Trimming what reviewers read is *not* where cost lives — measured, it
> saves little (agents read what their lenses need either way) and content is cached and
> paid once. The wins are the **minimal-toolset agents** (§2, −33% on a real review) and
> **skipping generated files** (hard rule 3). Do not trade review depth for tokens.

**Material caps (state what you drop — never drop silently).** Before spawning the panel:
- Skip any single file whose diff exceeds **~15k tokens** (~60KB) — list it as
  `not reviewed (too large)` in the overview with its size.
- Cap total diff material per MR at **~60k tokens**; if exceeded, review the highest-risk
  files first (source over config/tests/fixtures) and **name every file you skipped**.
- These caps are the skill's own "no silent caps" rule applied to itself. A skipped file
  is a **known gap**, not a covered one — say so in the overview and the verdict.

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

### 1c. Resolve the stack (review-core engine)

The review brain is the shared **`review-core`** engine
(`~/.claude/skills/review-core/`). Follow `review-core/references/resolver.md` on the
repo root: detect the base stack + library overlays and load the matching
`lenses/*.md` on top of the universal lenses. Record the one-line result to inject into
the persona prompts, e.g. `Stack: Flutter · packs: _base-flutter + flutter-mobx · repo
rules: CLAUDE.md, analysis_options.yaml, .review-memory`. Unknown stack →
**universal-only** (still a full review). This supplies the stack-appropriate idioms —
Go/Postgres, NestJS, Flutter-BLoC/MobX, … — instead of a hardcoded Flutter checklist.

### 2. Run the panel (5 agents, +1 when the MR has a ticket)

Spawn the agents **in parallel** (Agent tool, `run_in_background: true`): A/B/C/E/D
always, **and Reviewer F when the MR carries a ticket key or MR-description ACs**.

**Spawn A/B/C/E/F with `subagent_type: 'review-panel'` and D with
`subagent_type: 'review-build'`** — the plugin's own agent definitions, which carry a
**minimal toolset** (`Read, Grep, Glob, Bash`). Do **not** use `general-purpose`: it
re-sends ~100 unused MCP tool schemas on **every turn** — measured at **~5,420 tok/turn**,
i.e. ~83% of a reviewer's per-turn cost, for tools a code reviewer never calls
(a trivial 11-turn agent cost 71,479 tokens as general-purpose vs 11,857 with 4 tools).
Across a 5-agent panel at ~20 turns each that is **~540k tokens/round of pure schema
overhead**, and removing it costs nothing — the tools are unused. This is the single
largest saving in the pipeline; content is cached and paid once, so it is not where the
money is.

Personas are defined in `review-core/references/personas.md`; each applies the universal lenses
(`universal-lenses.md`, incl. complexity U11 + merge-conflict-via-`git merge-tree` U9)
plus the stack `lenses/*.md` the resolver loaded:

- **A — Architecture & Patterns**
- **B — Correctness & Edge Cases**
- **C — Performance & Code Quality**
- **D — Build & Analyze (CI parity)** — **spawn with `model: 'haiku'`**. Mechanical:
  mirrors the repo's **real CI** (reads `.gitlab-ci.yml`/`.github/workflows`, runs its
  exact lint/test/build incl. formatter gates and `//go:build` tags — not a generic
  build), checks head pipeline status, in an isolated `git worktree` cleaned before
  removal (never the user's checkout). **Give D a small context** — the branch, the CI
  config and the MR's file list; it does not need the diff body or any source.
- **E — Seams & Blast Radius** — the reviewer for code *outside* the diff: is the new
  thing wired (U5), drained like its siblings (U14), consistent with its neighbors
  (U13), and does the far-side consumer have a dedup key (U3)? Plus the **parallel-
  structure sweep**: a fix that adds a table entry / struct field / switch case whose
  **sibling of the same shape didn't get the same change** (real miss: !83's
  `tourTemplateErrorMappings`, !82's `TourExplorer.RatingCount`). Reads the composition
  root / sibling / consumer on demand.
- **F — Spec & AC Completeness** *(only when a ticket key or MR-description ACs exist)* —
  routes to the repo's Jira per `review-core/references/spec-ac.md` +
  `config/jira-routing.json` (by GitLab group; matches on site host so multiple Jira
  accounts coexist), fetches the ticket's acceptance criteria, and returns
  **done / partial / not-done** per AC with a `file:line`. A `partial`/`not-done` AC is a
  **P1** (ticket not delivered). Falls back to MR-description ACs when the routed Jira
  isn't connected; skipped silently when there's no ticket. Catches the
  `explorer-back!79/!82/!83` class where the fix was correct but incomplete vs its ACs.

**Per-agent scoping (keep the panel inside budget).** Pass each agent only what it owns:
its own persona section + the universal lenses it owns + the loaded pack(s). A/B/C get
the diff; E gets the diff's inventory of new things (it fetches the unchanged files it
needs); D gets neither. All reads beyond that are on demand — see `personas.md`
§ "Reading the code".

Build every persona prompt from the **common context block** in
`references/reviewer-prompts.md` (it loads personas.md + universal-lenses.md + the
loaded packs + repo CLAUDE.md/ADRs). Fill `<list>` with the resolver's loaded packs.
When `thread-context.md` exists (re-review), append the § Developer replies block.
Reviewers A–C return findings `{mr,file,line,severity,reviewer,category,title,body,snippet}`
+ one `{mr,reviewer,summary}` per MR (+ reply resolutions on re-reviews). Reviewer D
returns the build record from `personas.md` (`compiles`, `analyzer_errors/warnings`,
`ci_gates`, `pipeline`, reachability gaps).

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
          "head_sha": "b99e92c8…", "base_sha": "11ea4889…",
          "verdict": "✅ Approve | ⚠️ Approve with minor fixes | 🔄 Request Changes",
          "build": {"compiles": true, "analyzer_errors": 0, "analyzer_warnings": 12,
                     "tool": "dart analyze", "notes": ""},
          "conflicts": false,  "merge_status": "can_be_merged",
          "skipped_files": [{"path": "…", "reason": "diff > 15k tok", "size": "…"}],
          "conflicts_rechecked_at_delivery": true,  "snapshot_moved": false,
          "discussion": [{"by": "Davit", "quote": "this is intentional, backend clamps it",
                           "resolution": "deferred",
                           "response": "Accepted as deferred — add a TODO + ticket before merge."}],
          "fix_prompt": "--- FIX PROMPT --- …"}
}
```

On re-reviews, fill `discussion` per MR from the reviewers' reply resolutions (deduped): each entry renders in the report as a "💬 Thread follow-ups" block in that MR's overview. Resolutions: `resolved` (code proves the fix), `deferred` (author said later/out-of-scope — state the guardrail asked for), `disputed` (reviewer still disagrees — state why, cite code), `clarified` (author was right — finding withdrawn, say so plainly).

Set `conflicts` per MR from step 1's fetch — but **verify with `git merge-tree`, never the
API flag alone** (universal lens U9; the flag is lazily computed and goes stale). The
report shows it as a **Conflicts column**.

**Snapshot honesty.** Record `head_sha` + `base_sha` (the exact commits reviewed) in
`meta.json`, render both in the HTML report header, and put the **short head SHA** in the
Slack verdict message. A reader must be able to tell which snapshot a verdict describes —
without it, a later "but it conflicts now" is impossible to reconcile against what was
reviewed.

**Re-verify conflicts at DELIVERY time, not only at fetch time.** The target branch moves
while the panel runs (a real case: clean at 18:09, target advanced at 18:28, branch then
conflicted — the report still said clean). Immediately before sending:

```bash
git fetch origin <target> -q
git merge-tree $(git merge-base <head_sha> origin/<target>) <head_sha> origin/<target> | grep -c '^<<<<<<<' || true
glab api "projects/<enc>/merge_requests/<N>" --jq '.sha'   # has head moved since fetch?
```
If the head moved or the target advanced since the review, set `snapshot_moved: true` and
**say so in the verdict message** ("reviewed at `<short_sha>`; target has advanced since —
re-check conflicts") rather than silently reporting a stale result.

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
- Capture the ts that `msg.sh` prints from its **`MSG_TS=` line**, never with a naive `grep ts=` — the permalink line also contains `thread_ts=<digits>`, so `grep -o 'ts=[0-9.]*'` matches **both** and yields a garbled two-line value; passed to `send.sh` it silently drops the upload to the **channel root** (`thread_ts=None`) instead of the thread. Use: `TS=$(msg.sh … | sed -n 's/^MSG_TS=//p')`.
- **For the report upload (6b), pass the thread PARENT ts** — the anchor PR message (watch/Slack-URL case) or `MSG_TS` for a fresh DM. Do **not** pass a verdict-reply ts that is itself already a threaded reply: `files.completeUploadExternal` only threads under a real parent and drops non-parent ts to the channel root.
- **No CC token?** `msg.sh` exits `3`. Do **not** silently send via MCP. Stop and tell the user to run `~/.claude/skills/slack-send/install.sh` once (connects the CC App → posts as them and unlocks the report upload), then retry. Only if the user explicitly declines the install, fall back to the MCP connector for the verdict message alone (posts under the connector identity, **no file upload possible**) — and make that limitation explicit to the user.

**Step 6b — upload the HTML report into that thread:**

```bash
~/.claude/skills/slack-send/scripts/send.sh \
  "<Desktop path to mr-review-<Ns>.html>" \
  "<TARGET (channel ID for thread; user ID for DM)>" \
  "📄 Full review report" \
  "<thread PARENT ts — anchor PR message (watch/Slack-URL), or MSG_TS for a fresh DM; NOT a verdict-reply ts>"
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
- **Also emit one `reviews` roll-up per reviewed MR** — otherwise the verdict you just
  computed is thrown away and `/review-pr-stats` can never report approved vs
  request-changes:
  ```json
  "reviews": [{"mr": 57, "round": 2, "verdict": "🔄 Request Changes", "head_sha": "b99e92c8",
               "p0": 1, "p1": 3, "p2": 7, "build": "failed", "conflicts": false}]
  ```
  Counts are the canonical findings only (exclude `+1` replies). Stored as
  `kind:"review"`, excluded from recall — stats, never findings.
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

- **`review-core` skill** (`~/.claude/skills/review-core/`) — the shared review engine: the resolver (stack → lens packs), personas A/B/C/D/E, universal lenses U1–U14, and the per-stack `lenses/*.md`. This is where review quality is defined; this skill only adds Slack/HTML delivery on top.
- **`references/reviewer-prompts.md`** — delivery-only scaffolding: the common context block (which loads review-core), merge/dedupe rules, developer-reply handling, Slack target resolution & verdict-message template
- **`scripts/build_html.py`** — GitHub-style HTML report generator (reads `findings.json`, `meta.json`, `mr<N>.diff` from CWD)
- **`slack-send` skill** (`~/.claude/skills/slack-send/`) — the **required** delivery path for step 6: `scripts/msg.sh` posts the verdict message and `scripts/send.sh` uploads the HTML report into the thread, both as the reviewer. Needs a Slack user token in `~/.slack-upload-token`; see that skill's `README.md` / `install.sh`. The Slack MCP connector is read-only in this workflow (thread/user lookups) and is a message-only last resort **only** if the user declines installing the token.
- **`review-memory` skill** (`~/.claude/skills/review-memory/`) — per-repo learning layer. Step 1b `recall` and step 7 `record` go through `scripts/memory.py`. Calibrates reviews from past outcomes + developer responses; never overrides CLAUDE.md/ADRs.
