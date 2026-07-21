# Spec / AC completeness (Reviewer F) + repo-based Jira routing

The panel's A–E personas answer *"is this diff correct?"*. They do **not** answer
*"does this diff satisfy everything the ticket asked for?"* — because nothing feeds them
the ticket. This file adds that axis: fetch the originating issue's **acceptance
criteria** from the **right** Jira (per repo), then judge each AC against the code,
explicitly including paths **outside** the diff.

Why it exists — measured misses on real MRs a human (not the panel) caught:
- `explorer-back!82` (COM-801): fix correct on `domain.Explorer`, but `domain.TourExplorer`
  (the guide summary on `GET /tours`) has no `RatingCount` field at all — **same bug,
  sibling struct, different endpoint**. Invisible to a diff-only review.
- `explorer-back!83` (COM-810): fix correct on `tourErrorMappings`, but the sibling
  `tourTemplateErrorMappings` **in the same file** has none of the 4 sentinels → template
  create still 500s. **AC1 partial — not done.**
- `explorer-back!79` (COM-800): AC3 ("already-listed location shows guides") **not done** —
  the fallback only runs after a successful resolve. An AC the fix never satisfies.

Two of the three are also caught by Reviewer E's new **parallel-structure sweep**
(personas.md, U13); the AC axis is what catches the third and frames all of them as
"ticket promised X, code delivers X-minus".

---

## Step 1 — Route to the correct Jira (repo-based)

MCP auth is **per-connection and static for a session** — you cannot hot-swap Jira
accounts mid-run. Instead, several Atlassian MCP servers may be connected at once, each
authed to a different account/site; this step picks the right one **per MR** without
hardcoding server IDs (they are hashed per connection).

1. **Derive the GitLab group** from the MR URL: the first path segment after the host,
   e.g. `https://gitlab.com/dz44-group/explorer/explorer-back/-/mr/84` → `dz44-group`.
2. **Look up the target site** in `config/jira-routing.json`: first `routes[]` entry whose
   `gitlab_group` matches (exact, or `*` wildcard), else `default.jira_site`.
3. **Find the connected server that can reach it.** For each available Atlassian MCP
   (discover via ToolSearch: `getAccessibleAtlassianResources` / `getJiraIssue`), call
   `getAccessibleAtlassianResources` and use the server whose result lists the target
   `jira_site` (match on `url` host). Record its `cloudId` for the issue fetch.
   - No connected server reaches the target site → the routed Jira isn't connected yet.
     Do **not** fall back to a *different* account's Jira (wrong ACs are worse than none):
     go straight to Step 2's fallback and note "Jira `<site>` not connected" in the pass.

## Step 2 — Get the acceptance criteria

1. **Extract the ticket key** from the MR title or source branch:
   `/\b([A-Z]{2,}-\d+)\b/` — e.g. `[COM-810]`, `MONE-909`, branch `COM-803-live-…`.
   Multiple keys → fetch each. None → skip the AC pass (note "no ticket key on MR").
2. **Fetch the issue** on the routed server: `getJiraIssue(cloudId, key)`; read the
   description + any "Acceptance Criteria" / AC checklist / Gherkin blocks. Also pull
   linked issues if the ACs reference them.
3. **Fallback (`ac_source_fallback: "mr_description"`)** — when the routed Jira is
   unreachable, parse ACs from the **MR description** instead (look for an "AC" /
   "Acceptance Criteria" / checkbox / "Done when" section). If neither exists, the pass
   emits a single note: "no acceptance criteria available (Jira `<site>` not connected,
   MR description has none)" — never fabricate ACs.

## Step 3 — Reviewer F — Spec & AC Completeness

Spawn as one more panel seat (same `review-panel` agent type as A/B/C/E). Give it: the
ticket key(s) + the extracted ACs, the diff, and read-on-demand access to the repo.

For **each acceptance criterion**, return a verdict:
- **done** — cite the `file:line` that satisfies it.
- **partial** — satisfied on one path, missing on a sibling path. Name the covered path
  AND the uncovered one with `file:line` (e.g. "handled in `tourErrorMappings` but not
  `tourTemplateErrorMappings:44`"). Severity ≥ **P1** — the ticket is not delivered.
- **not-done** — no code satisfies it; state what a user still hits (e.g. "unresolvable
  stored place_id still returns 400, AC3 says it must show guides"). Severity **P1**.
- **out-of-literal-scope but same user-visible symptom** — the ticket's wording is
  narrow, but an identical bug exists on a sibling surface (e.g. `TourExplorer` missing
  `RatingCount`). Report as **P2** and say "scope call needed", don't assert it as a
  blocker — mirror how a careful human flags it.

Hard rules (inherited): FACT vs ASSUMPTION — every verdict cites exact code; verify at
HEAD. "The description says it's done" is not evidence; the code is. An AC you cannot
map to code is `not-done`, not `assumed-done`.

Output per AC: `{mr, ac_id, ac_text, verdict, covered_ref, gap_ref, severity, note}`, plus
one `{mr, reviewer:"F", summary}` roll-up. `partial`/`not-done` verdicts also become
normal findings (so they land in the report + fix prompt).

## Wiring notes for front-ends

- `review-pr-slack` and `/review-pr` both spawn F **in parallel** with A/B/C/E when a
  ticket key is present. When no key and no MR-description ACs exist, skip F silently
  (one line in the overview: "AC pass skipped — no ticket").
- F's `partial`/`not-done` findings feed the same dedupe/report path as the others and
  are counted in the verdict (a `not-done` AC is a P1 → Request Changes).
- Keep F **advisory on wording, strict on delivery**: it judges whether the *shipped
  behavior* meets the ACs, not whether the author phrased the ticket well.
