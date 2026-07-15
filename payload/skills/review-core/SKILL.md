---
name: review-core
description: Shared, stack-aware review engine for pr-review-loop. Not invoked directly by users — the /review-pr command and the review-pr-slack skill both load it to get the reviewer personas (A/B/C + Reviewer D build/CI), the universal stack-agnostic lenses, and the pluggable per-stack lens packs selected by a resolver. Detects the repo's stack + libraries (Flutter BLoC/MobX/Riverpod/Provider, Go/Postgres, NestJS, …), loads the matching lens packs on top of universal principles and the repo's own CLAUDE.md/ADRs/linter/review-memory, and falls back to universal-only for unknown stacks. Read this when running any pr-review-loop review, or when adding/editing a stack lens pack.
version: 1.0.0
---

# Review engine (review-core)

The single source of truth for **how** pr-review-loop reviews — personas + lenses.
The delivery front-ends decide **where** findings go:
- `/review-pr` (command) → inline GitLab/GitHub comments + overview + fix prompt.
- `review-pr-slack` (skill) → HTML report + Slack verdict, never posts on the platform.

Both call this engine so review quality is identical and defined once.

## What the engine provides

| File | Role |
|---|---|
| `references/resolver.md` | Detect stack + libraries → choose which lens pack(s) to load. Run FIRST. |
| `references/universal-lenses.md` | U1–U12: stack-agnostic review principles (the WHAT). Always applied. |
| `references/personas.md` | Reviewers A/B/C + **D (Build & Analyze, CI-parity + reachability)**. |
| `references/lenses/<stack>.md` | Per-stack idioms (the HOW). Loaded on demand by the resolver. |
| `references/lenses/README.md` | Pack contract — how to author/extend a stack pack. |

## How a front-end uses it (the contract)

1. **Resolve** — follow `resolver.md` on the repo root: detect base stack + overlays,
   print the "Stack: … · packs: … · repo rules: …" line. Unknown stack → universal-only.
2. **Assemble the panel** — spawn Reviewers A/B/C (and D on the build path) from
   `personas.md`. Into every persona prompt inject, in precedence order:
   `universal-lenses.md` → the loaded `lenses/*.md` → repo `CLAUDE.md`+ADRs → repo
   linter config → `.review-memory` recall (+ `thread-context.md` on re-reviews).
   The repo's own rules always outrank a generic pack.
3. **Review** — each persona applies its owned universal lenses + the pack rules,
   reporting only FACTS (exact code) with P0/P1/P2 severities.
4. **Deliver** — the front-end formats/dedupes/posts (see its own SKILL/command).

## Non-negotiables (inherited by both front-ends)
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
