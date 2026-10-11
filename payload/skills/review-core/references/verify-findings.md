# Verify findings before delivery

Two checks run between the panel and delivery. The first is code, the second is a
cheap model pass. Neither adds findings — they correct and prune what the panel
produced. `/review-pr` runs them as step 5d.

| Stage | When | What | Cost |
|---|---|---|---|
| 1 · Re-locate | after the panel returns, **before** merge & dedupe | `scripts/relocate-findings.py` moves each finding to the line its snippet is on and classifies it as inline-anchorable or not | zero tokens |
| 2 · Fact-check | after merge & dedupe (and stack attribution) | `review-filter` agent (haiku) drops only findings the code proves wrong | one small agent |

Why (both stages are adapted from OpenCodeReview, Alibaba's review CLI, which runs
them as dedicated modules after its review agent): skill-driven reviewers lose findings in two ways that no prompt
fixes reliably — the line number drifts off the code it describes, and a confident
but wrong claim reaches the author with nothing to stop it. A code check fixes the
first. A narrow pass that may drop only proven-wrong findings handles the second
without costing recall.

## Stage 1 — re-locate

Reviewers already return `snippet` (personas.md § Finding shape). It must be copied
**verbatim from the file at HEAD**, 1–3 lines, including the line the finding is
about. The snippet is the evidence; `line` is a hint.

```bash
python3 ~/.claude/skills/review-core/scripts/relocate-findings.py \
  --repo <checkout> --ref <head_sha> --base <merge_base_sha> \
  --in raw-findings.json --out findings.json
```

In stack mode `--ref` is the **tip** and `--base` is `merge-base(main, tip)` — the
same cumulative diff the panel reviewed.

Each finding gains `original_line`, `relocation`, and `anchor`:

| `relocation` | Meaning | Do |
|---|---|---|
| `exact` | snippet is at the reported line | nothing |
| `moved` | snippet found elsewhere; `line` corrected (`relocation_delta`) | use the new line |
| `fuzzy` | only a close match found; `line` set to it | use it, and let stage 2 look |
| `not_found` | quoted code is not in the file at HEAD | keep `line`; stage 2 gets the signal |
| `no_snippet` / `no_file` | nothing to check against | stage 2 reads the file |

| `anchor` | Delivery |
|---|---|
| `added` | inline comment, `new_line` only |
| `context` | inline comment, `new_line` **and** `old_line` (the script supplies it) |
| `outside` / `no_diff` | MR-level note with `` `path` : line N `` in the body |

This replaces discovering anchorability one failed POST at a time. Run it before
merge & dedupe so duplicates from different reviewers land on the same corrected
line and thread together.

A `moved` count above a few per round means a reviewer prompt is giving line numbers
from hunk headers or the base side — worth fixing at the source.

## Stage 2 — fact-check

Spawn **one** `review-filter` agent (`subagent_type: 'review-filter'`,
`model: 'haiku'`) with `repo`, `head`, `base` and **only the canonical findings whose
`relocation` is `not_found`, `fuzzy` or `no_snippet`** (`+1` replies excluded — they
follow their canonical). A snippet that matched the code exactly is already grounded:
across a 2-PR benchmark the filter dropped none of them, while costing 20–51 turns per
run. No doubtful findings → skip stage 2 entirely. It returns a verdict per
finding: `keep`, or `drop` with a ground (A: not in the file / B: a line
contradicts it) and the quoted `file:line` that proves it.

Rules the caller enforces on the result:

- **Never drop on a verdict without `evidence`.** Treat it as `keep`.
- **P0/P1 are never dropped** even if the agent says so — they are protected in its
  prompt; a `drop` on one means the prompt was ignored. P2s in protected categories
  (resource safety, concurrency, security, behaviour change, build) can be dropped only
  on Ground A with a `not_found` snippet. Keep it and add the agent's
  evidence as a note for yourself to check before posting.
- Dropped findings are **not deleted silently**. List them in the overview under
  **Filtered by fact-check** — one line each: title, `file:line`, ground, evidence.
  A wrong drop is then still visible to the author.
- Re-reviews: findings carried over from a prior round (`Still unresolved`) skip
  stage 2 — they were checked when first raised, and thread state decides them now.

Leave dropped findings out of `decisions.json` — they were never delivered, so there
is no developer response to learn from.
