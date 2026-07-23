# Stack-level review — reviewing a chain as one unit

Both front-ends load this. It covers **detecting** a stacked chain, **asking the merge
policy**, **reviewing the cumulative diff**, **attributing findings back to the MR that
introduced them**, and **the single verdict**.

Why it exists: a 10-deep chain reviewed MR-by-MR produced **18 findings already fixed by
a later MR in the same chain**, plus one recommendation that would have broken the build.
The root cause is not a missing check — it is reviewing **intermediate states that never
reach `main`**. A per-MR review of MR 3 of 10 judges a tree nobody will ever run.

---

## 1. Detect the chain

After fetching the MR/PR list, build the **target → source** graph across the open MRs:

- An MR is **stacked** when its **target branch equals another open MR's source branch**.
- Order the chain bottom → top by following target→source links.
- The **stack tip** is the MR whose source branch is nobody else's target.
- An MR targeting `main`/`master` with **no children** is **independent** — it keeps the
  existing per-MR path. Nothing below applies to it.
- Several independent chains can coexist in one batch. Resolve each separately.

Emit one line before anything else:

```
Stack detected: !41 → !42 → !43 → … → !53 (10 MRs, tip = MONE-975-add-chips-to-multiple-selectable-options)
```

```bash
# GitLab: every open MR's source + target, to build the graph
glab api "projects/<enc>/merge_requests?state=opened&per_page=100" \
  --jq '.[] | "\(.iid)\t\(.source_branch)\t\(.target_branch)"'
# GitHub
gh pr list --repo OWNER/REPO --state open --json number,headRefName,baseRefName
```

A single MR whose target is another open MR's source is still a chain of two — the
policy question below applies to it exactly the same way.

### Assert the chain is merged forward — before reviewing anything

Stack mode reviews the **tip** on the premise that the tip contains the whole chain. Verify
that; never assume it. For every branch below the tip:

```bash
for b in "${CHAIN[@]}"; do
  git merge-base --is-ancestor "origin/$b" "$TIP_SHA" \
    && echo "$b in tip" || echo "$b NOT IN TIP"
done
```

**Any `NOT IN TIP` means the stack cannot be reviewed at its tip yet.** Say so and stop —
a verdict computed from a tip that is missing its parents' work describes a tree nobody
will run, which is the exact failure this mode exists to prevent. Ask the authors to merge
each branch forward into its child, bottom to top, and re-run afterwards.

This is easy to miss because **every MR looks freshly updated**. On the real `!41 → !53`
chain each of the ten branches independently received its own "bump `design_system` to
v1.0.15" commit on the same afternoon, so every head had a new timestamp and every MR
reported `mergeable` — while the tip contained none of the accompanying fixes, including a
new bloc test added on the bottom MR. The per-MR "did the dev push?" check said yes ten
times; the ancestry check said the tip was the oldest state in the chain.

Running the build gate on such a tip produces a **misleading green**. Report it explicitly
as a stale snapshot if you report it at all.

---

## 2. Ask the merge policy — this decides correctness

**Stack-level review is only correct if the chain merges atomically.** If the MRs land on
`main` one at a time over days, each intermediate state really does reach `main`, and
per-MR review of it is legitimate — not a bug. Getting this wrong in the other direction
is just as bad as the failure that motivated this mode.

**Ask the user once per chain (AskUserQuestion). Never guess, never infer from branch
names or MR descriptions.** Present the detected chain line, then:

| Answer | Meaning | Mode |
|---|---|---|
| **atomic** | the whole chain merges together (one merge train / merge-when-all-approved) | **full stack mode** — §3 |
| **piecemeal** | each MR merges to `main` separately, over time | **hybrid** — §3 for correctness/architecture/AC, **plus a per-MR build gate** |

The **piecemeal build gate** is narrow on purpose. Per MR, Reviewer D answers exactly one
question: **"does this MR alone leave `main` compiling?"** It is not a second review — no
architecture, no style, no AC. A per-MR build failure is a P1 on **that** MR even when the
stack tip is green, because that broken intermediate state does reach `main`.

In unattended `/loop` mode there is no one to ask: **default to piecemeal** (the strictly
safer answer — it adds the per-MR build gate rather than removing a check) and say in the
verdict which policy was assumed.

---

## 3. Review the stack

**Review the cumulative diff as ONE unit:**

```bash
git fetch origin <base> <tip-source-branch> -q
git merge-base origin/<base> origin/<tip>          # -> BASE_SHA
git diff BASE_SHA..origin/<tip>                    # the material to review
```

Every file is read at its **final state**. This is also less work, not more: on the real
10-MR case the cumulative diff was **130 non-generated files vs 165 per-MR file-touches**,
because files edited by three MRs were reviewed once instead of three times.

Rules:

- **Material caps and generated-file skipping apply to the cumulative diff**, unchanged.
  Name every file the caps drop, as always.
- **Build:** once at the tip (atomic), or once per MR (piecemeal — the narrow gate above).
- **ACs (Reviewer F):** collect the ticket for **every MR in the chain**, verify all of
  them against the **final state**, and if the tickets share a parent epic, check the epic
  too. An AC satisfied anywhere in the chain is `done` — that is the whole point.
- **Reviewer E matters more here, not less.** The composition root at the tip is the
  **real** one: what is wired, drained and consistent at the tip is what actually ships.
  U5/U13/U14 findings from an intermediate state were the bulk of the 18 false findings.
- **U9's stacked-tip check becomes structural.** In stack mode you are already at the tip,
  so "not wired / no caller / never published / does not exist" is judged against the code
  that ships. Still read, never grep for an assumed symbol, and still follow `part`/
  `part of` (and equivalent include/split) declarations before calling anything unused.

---

## 4. Attribute findings back to the introducing MR

Findings carry **tip-relative `file:line`**, but each must still land on the MR that
introduced it so the right author gets their own comments.

Mechanism, per finding: blame the line at the tip → commit SHA → the **lowest branch in
chain order** whose history contains that SHA. Shipped as
`scripts/attribute-findings.sh` (in the plugin root, not the skill payload):

```bash
scripts/attribute-findings.sh --repo <dir> --tip origin/<tip-branch> \
  --chain <br1,br2,…,brN>   # bottom -> top; `x`, `origin/x` and `refs/…` all accepted
  --base origin/main        # optional; auto-detects origin/main|main|origin/master|master
# single finding:  --file <path> --line <N>
# batch:           printf 'path/a.dart:36\npath/b.dart:12\n' | …
# out (TSV):       file <TAB> line <TAB> branch <TAB> short-sha
```

**Verified on the real 10-MR chain** (112 commits, `MONE-749-ld-setup-foundation` →
`MONE-975-add-chips-to-multiple-selectable-options`): the `SelectionCard` probe in
`…/logistic_and_delivery_setup/presentation/widgets/fulfillment_methods.dart` resolves to
`MONE-749` (!41) as expected, and a 130-line sweep across the cumulative diff attributed
to all 10 MRs with **no misattributions**.

**Two failure modes the script exists to prevent** — both produce a silently wrong map:

1. `git branch --contains <sha>` **without `-a`** sees only *local* branches. A freshly
   fetched stack has every branch under `refs/remotes/origin/`, so it returns nothing and
   attribution looks broken. (This is why a hand-run probe of this idea came back empty.)
   The script uses `git for-each-ref --contains` over local **and** remote refs.
2. Every chain branch descends from the base, so a commit **already on `main`** is
   "contained" by all of them and would attribute to the **bottom** MR. Findings are
   explicitly not limited to changed files, so blaming pre-existing code is routine. The
   script rejects those via a `--base` ancestor test.

**Unattributable findings are normal — never guess an author.** Rows come back as
`UNKNOWN` with a reason (`pre-existing`, `no-such-file`, `line-out-of-range`,
`not-in-chain`). Post each on the **tip MR** with the originating file named. On the real
sweep every `UNKNOWN` was legitimate (25 pre-existing, 2 out-of-range).

If the script cannot run at all (shallow clone, chain branches not fetched, blame fails
wholesale), **say so plainly in the overview and post all findings on the tip MR with the
originating file noted.** Do not ship a partial or guessed mapping.

---

## 5. Reconcile the previous round's threads — do not skip this in stack mode

Stack mode replaces *how the diff is assembled*, *not* the re-review flow. Step 4b of
`/review-pr` (classify every open thread, reply, resolve) still applies, and applies to
**every MR in the chain**, not just the tip.

It is easy to lose: the chain-detection and cumulative-diff work happens before the panel,
so the natural next move is to spawn reviewers and post a new round — leaving the previous
round's threads open and the author's replies unacknowledged. On the real `!35 → !36`
review this is exactly what happened: 39 threads carried author replies of the form
"Fixed in `<sha>`" and **none** were resolved, while the new round's overview asserted the
prior blockers were fixed on the strength of 5 spot-checks out of 39.

Two rules:

- **A new round is owed whenever commits landed after the previous round's comments.**
  Compare each MR's newest review-comment timestamp against its commit dates; that is the
  trigger, per MR, independent of the stack.
- **Verify every "fixed" claim at the tip before resolving** (U9). The author's word is
  not evidence, and neither is `resolved=true`. Read the code. Locate it **by content** —
  the `file:line` in the old comment is stale by construction, since the fix changed the
  file. A consolidation ("I replaced X with the shared Y") can move a defect rather than
  remove it, so go read Y and confirm it has the property the finding demanded.

Never bulk-resolve, and never delete the previous round's comments to "supersede" them —
the author's in-thread replies are the record of what changed and why.

```bash
# GitLab: reply, then resolve
glab api --repo "$REPO" -X POST \
  "projects/:id/merge_requests/$IID/discussions/$DISCUSSION_ID/notes" -f body="✅ Resolved — <evidence>"
glab api --repo "$REPO" -X PUT \
  "projects/:id/merge_requests/$IID/discussions/$DISCUSSION_ID?resolved=true"
```

Anything that does not hold up gets `⚠️ Still unresolved — <what remains>` and stays open;
it also carries into the new round's overview under **⚠️ Still Open from previous rounds**.

## 6. Verdict

**One verdict for the stack**, computed from the cumulative review under the existing
policy (conflicts OR broken build OR **unverified** build OR any P0/P1 → Request Changes).

Each MR in the chain gets a **short note pointing at the stack overview** — never its own
contradictory verdict. An MR whose own diff looks clean is not "Approve" when the stack it
belongs to is blocked:

```
Reviewed as part of stack !41 → !53 (10 MRs, atomic). Findings attributed to this MR: 3.
Stack verdict: 🔄 Request Changes — see the overview on !53.
```

In **piecemeal** mode a per-MR build failure is the one thing that also blocks that MR on
its own; say which of the two blocked it.

Record memory as usual: one entry per canonical finding under **the MR attribution
resolved**, and the `reviews` roll-up under the **tip** MR with the chain noted.
