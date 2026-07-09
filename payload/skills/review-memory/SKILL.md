---
name: review-memory
description: This skill should be used by the code-review skills/commands (/review-pr, /review-pr-slack, /review-codequality, /review-functional-logic, /review-security-performance, /review-context-maintenance, code-review, review-changes) to recall past review outcomes before reviewing and record new outcomes after. Also invoke it directly ("distill review memory", "what has review memory learned for this repo") to review and promote recurring lessons. Maintains a per-repo `.review-memory/` corpus (committed) of findings + developer responses that calibrates future reviews without ever overriding CLAUDE.md / ADRs.
version: 1.0.0
---

# Review Memory

Per-repo learning layer for the code-review skills. Each repo carries a committed
`.review-memory/` corpus of past findings and how developers responded to them
(resolved / deferred / disputed / clarified). Reviews **recall** it before
reviewing and **record** into it after. Recurring confirmed lessons are promoted
by a human into the repo's CLAUDE.md / ADRs.

## Why per-repo, not shared

The same review skill runs on different repos with different architectures — a
MobX Flutter app and a BLoC Flutter app share a language but oppose each other's
rules. A shared corpus would cross-contaminate. Memory is therefore keyed to the
repo (its `.review-memory/` folder), which lines up exactly with what already
governs the repo: its own CLAUDE.md + ADRs.

## Authority hierarchy (never invert)

1. **CLAUDE.md + ADRs** — authoritative, hand-written. Read first.
2. **`.review-memory/rules.md`** — curated, human-approved distilled rules. Extra
   reviewer context. Loses to CLAUDE.md/ADRs on any conflict.
3. **`.review-memory/decisions.jsonl`** — raw outcome log. Calibrates confidence
   (cuts repeat-noise, honors prior deferrals). Never a rulebook on its own.

Memory only *calibrates* a review. It never invents rules or overrides the
repo's documented standards. A finding still has to be provable against the
current code (FACT vs ASSUMPTION) — a prior "resolved" is a hint to re-verify,
not a reason to skip checking.

## The tool

All operations go through `scripts/memory.py` (python3, stdlib only; graphify is
an optional semantic layer). Run it against the repo root (`.`).

### Recall — before reviewing

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py recall . --area "<changed features / paths / keywords>"
```

Prints: the curated `rules.md`; a **DO NOT RE-RAISE** list (findings the author
previously resolved/disputed/clarified — skip unless the code materially
changed); and a **DEFERRED — verify the guardrail landed** list. Feed this to the
reviewer agents as calibration context. New repo with no memory → prints a notice
and you review normally.

### Record — after the review is finalized

Build a small JSON payload of this round's findings plus any developer responses,
then:

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py record . --input decisions.json
```

Payload shape:

```json
{
  "stack": "flutter-bloc",
  "commit": "<head sha>",
  "date": "<YYYY-MM-DD>",
  "entries": [
    {"mr": 58, "file": "lib/.../foo_bloc.dart", "line": 70,
     "category": "Correctness", "severity": "P1",
     "title": "OTP code never validated",
     "dev_resolution": "deferred",
     "rationale": "backend handles in PROJ-901; gate behind flag",
     "reviewer": "B", "round": 2}
  ]
}
```

- `dev_resolution` ∈ `open | resolved | deferred | disputed | clarified`. Round 1
  findings are usually `open`; on re-reviews, fill it from the developer's thread
  replies (the /review-pr-slack "Thread follow-ups" resolutions map 1:1).
- **Do not pass `signature`.** It is auto-derived from `file + title + category`
  and is stable, so the same finding across rounds links automatically. Only pass
  one explicitly if you are deliberately merging two differently-titled findings.
- Keep the finding `title` consistent across rounds so re-reviews link to the
  original entry.

### Watch items — human carry-forward directives

Distinct from bot findings: a **watch item** is a human saying "this needs
attention in future reviews" — e.g. complex logic that wasn't traced, a fragile
area to keep an eye on. It is tagged to a file/area, surfaces at the **top** of
recall in **every** future review touching that area (across PRs, not just
rounds), and is **sticky** — it stays open until a human explicitly closes it; it
does not auto-close just because the bot didn't re-raise it.

Add one:

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py note . \
  --by "<name>" --severity P1 \
  --area "lib/.../foo_mapper.dart merge sort" \
  --title "Merge/sort logic not fully verified" \
  --text "Trace ordering + tz handling in any PR touching this mapper."
```

Close it once checked:

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py close . \
  --signature "<sig from recall>" --resolution clarified --note "traced, OK"
```

Review skills must treat recalled watch items as **must-inspect this round** and
report on them, not skip them. When a human leaves a carry-forward comment in a
PR/Slack thread ("this complex logic wasn't checked — verify next time"), record
it as a watch item, not a finding.

### Distill — periodic, human-gated

```bash
python3 ~/.claude/skills/review-memory/scripts/memory.py distill .
```

Lists signatures seen repeatedly with their resolution mix. **A human** promotes
confirmed lessons into CLAUDE.md / a new ADR (authoritative), or adds a curated
bullet to `.review-memory/rules.md`. Nothing is applied automatically — this is
the only path that changes review behavior, and it stays reviewed. Once a lesson
is codified in CLAUDE.md/ADR, its `rules.md` bullet can be removed.

For a semantic cluster view, build the graph once with the `/graphify` skill on
the `.review-memory` folder, then `graphify cluster-only .review-memory`.

## graphify (optional semantic layer)

`record` runs a fast, no-LLM `graphify update` so `graphify query` recall stays
fresh; `recall` adds a semantic pass when a graph exists. Everything works without
graphify — JSONL + rules.md recall is the deterministic source of truth. To build
the full semantic graph (LLM extraction + community detection) run the `/graphify`
skill on the `.review-memory` folder occasionally, not per-review.

## Integration contract for review skills

Every review skill wires two steps:

- **Recall** right after loading CLAUDE.md/ADRs, before analysis. Pass the changed
  features/paths as `--area`. Treat output as calibration, subordinate to
  CLAUDE.md/ADRs.
- **Record** once the review (and any developer thread replies) is finalized, with
  `dev_resolution` filled per finding.

`.review-memory/` is committed to the repo (heavy `graphify-out/` is gitignored),
so the whole team shares the memory and it is reviewed via PR.

## Additional Resources

- **`scripts/memory.py`** — the recall/record/distill/init/stats CLI.
