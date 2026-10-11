---
name: review-core
description: Stack-aware review engine for pr-review-loop. Not invoked directly by users — the /review-pr command loads it to get the reviewer personas (A/B/C + Reviewer D build/CI), the universal stack-agnostic lenses, and the pluggable per-stack lens packs selected by a resolver. Detects the repo's stack + libraries (Flutter BLoC/MobX/Riverpod/Provider, Go/Postgres, NestJS, …), loads the matching lens packs on top of universal principles and the repo's own CLAUDE.md/ADRs/linter/review-memory, and falls back to universal-only for unknown stacks. Read this when running any pr-review-loop review, or when adding/editing a stack lens pack.
version: 1.0.0
---

# Review engine (review-core)

The single source of truth for **how** pr-review-loop reviews — personas + lenses.
The delivery front-end decides **where** findings go:
- `/review-pr` (command) → inline GitLab/GitHub comments + overview + fix prompt.

## What the engine provides

| File | Role |
|---|---|
| `references/resolver.md` | Detect stack + libraries → choose which lens pack(s) to load. Run FIRST. |
| `references/universal-lenses.md` | U1–U14: stack-agnostic review principles (the WHAT). Always applied. |
| `references/personas.md` | Reviewers A/B/C + **D (Build & CI parity, runs on haiku)** + **E (Seams & Blast Radius: U5/U13/U14 + parallel-structure sweep)** + **F (Spec & AC completeness)**, the "Reading the code" contract (diff in, reads on demand), the **House conventions / owned-code** rule, and the **reporting cap** (P0/P1 threaded, P2s digested). |
| `references/stack-mode.md` | **Stacked chains**: detect the chain, ask the merge policy (atomic vs piecemeal), review the cumulative diff at the tip as ONE unit, attribute findings back to the introducing MR, one verdict. Run after the resolver whenever >1 MR is in play. |
| `references/verify-findings.md` | Between panel and delivery: **re-locate** findings by snippet (`scripts/relocate-findings.py`, deterministic, also classifies inline-anchorability) and **fact-check** them (`review-filter` agent, haiku — drops only proven-wrong findings, never P0/P1). |
| `scripts/relocate-findings.py` | The re-locator. Stdlib Python; tests in the plugin's `tests/test_relocate.py`. |
| `references/spec-ac.md` | Reviewer F procedure: repo→Jira routing, AC extraction, per-AC verdicts, MR-description fallback. |
| `config/jira-routing.json` | Repo (GitLab group) → Jira site map used by the AC pass. Matches on site host, not hashed server IDs, so multiple Jira accounts coexist. |
| `references/lenses/<stack>.md` | Per-stack idioms (the HOW). Loaded on demand by the resolver. |
| `references/lenses/README.md` | Pack contract — how to author/extend a stack pack. |

## How a front-end uses it (the contract)

1. **Resolve** — follow `resolver.md` on the repo root: detect base stack + overlays,
   print the "Stack: … · packs: … · repo rules: …" line. Unknown stack → universal-only.
1b. **Detect stacked chains** — with >1 MR in play, follow `stack-mode.md`: print the
   chain map, **ask the merge policy** (atomic → review the cumulative diff at the tip as
   one unit; piecemeal → the same plus a per-MR "does this alone leave `main` compiling?"
   build gate). Independent MRs keep the per-MR path.
2. **Assemble the panel** — spawn Reviewers A/B/C (and D on the build path, E for seams,
   and **F when the MR carries a ticket key or MR-description ACs** — route to the repo's
   Jira per `spec-ac.md`) from `personas.md`. Into every persona prompt inject, in
   precedence order:
   `universal-lenses.md` → the loaded `lenses/*.md` → repo `CLAUDE.md`+ADRs → repo
   linter config → `.review-memory` recall (+ `thread-context.md` on re-reviews).
   The repo's own rules always outrank a generic pack.
3. **Review** — each persona applies its owned universal lenses + the pack rules,
   reporting only FACTS (exact code) with P0/P1/P2 severities.
3b. **Verify** — re-locate (before dedupe) and fact-check (after) per
   `verify-findings.md`. Deterministic line correction first, then one cheap pass that
   may drop only what the code proves wrong.
4. **Deliver** — the front-end formats/dedupes/posts (see its own SKILL/command).

## Non-negotiables (inherited by the front-end)
- **Delivery is capped, detection is not** (`personas.md` § Reporting). P0/P1 always get
  their own thread; P2s go in the overview digest by default, at most 10 P2 threads per
  round and 25 inline threads total. Over the cap, digest the remainder. A review the
  author skims is worse than a shorter one they read.
- **Owned code raises severity, invented conventions are not findings**
  (`personas.md` § House conventions). A change to boilerplate/vendored/widely-imported
  code is P1 when it alters behaviour or generated output for callers outside the feature.
  A convention with zero existing uses in the repo is a suggestion, never a blocker.
- FACT vs ASSUMPTION: a finding must cite exact code; verify claims at HEAD, not from
  `resolved=true`/stale merge flags (universal lens **U9**).
- Skip generated files (`*.g.dart`, `*.freezed.dart`, `*.gen.dart`, `*.pb.go`,
  `*_gen.go`, `dist/`, `node_modules/`, lockfiles, …); extend from repo CLAUDE.md.
- Reviewer D never touches the user's checkout — worktrees only.
- Review memory calibrates but never overrides CLAUDE.md/ADRs.

## Adding a stack
Drop a new file in `references/lenses/` following `lenses/README.md`, then add its
detection row to `resolver.md`. No front-end change needed — that's the whole point of
the split.
