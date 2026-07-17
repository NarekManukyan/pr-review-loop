# Universal lenses — stack-agnostic review principles

These apply to **every** review regardless of language or framework. They are the
"WHAT to look for"; the loaded stack lens pack (`lenses/<stack>.md`) supplies the
"HOW it looks in this syntax". A finding here is only real if you can point at exact
code (FACT, not assumption). Severity: **P0** crash/data-loss/security/broken feature ·
**P1** significant bug/arch violation/serious perf · **P2** smell/minor.

Each lens below names the *principle*, the *smell to grep for*, and the *required end
state*. When a stack pack gives the concrete form, cite it; otherwise reason from the
principle in the repo's own idiom.

---

## U1 — Check-then-act races (TOCTOU)
**Principle:** any read → decide → write on shared state (a row, a counter, a balance,
a status) at a non-serializable isolation level can interleave. The decision must be
enforced *at the write*, not between two statements.
**Smell:** `SELECT`/`find` then a separate `UPDATE`/`save` with no lock; an
optimistic in-memory toggle with no compare-and-set; a "check limit then insert".
**Required:** put every column the decision depends on into a guarded write
(`UPDATE … WHERE <precondition> RETURNING`, check rows-affected == 0) or take a row
lock (`SELECT … FOR UPDATE`) inside the same transaction; for UI, an optimistic update
must roll back on failure and guard re-entrancy. → stack packs give the exact primitive.

## U2 — Write-plus-side-effect atomicity
**Principle:** a state change and its emitted event / outbox row / remote call must
commit together, or the system ends inconsistent after a crash between them.
**Smell:** `repo.Create(x)` followed by a separate `publish(evt)` / `emit()` /
external API call not wrapped in one transaction; "row exists but event never sent".
**Required:** single transaction (transactional outbox, `RunInTx`, `@Transaction`), or
an idempotent reconciler that repairs the gap. Name the crash window in the finding.

## U3 — Idempotency on money & events
**Principle:** anything that moves money or emits an event will be retried
(client retry, at-least-once queue, pod restart). Duplicate effects must be impossible.
**Smell:** no idempotency key on a create/charge; a key generated fresh per attempt
(`uuid.New()` in the call, not derived from a stable row id); a key that doesn't reach
the downstream service on the wire.
**Required:** a stable, deterministic idempotency key derived from the originating
entity, persisted, checked before effect, and propagated to every hop.

**Producer-side event IDs (cross-service).** For any event another service/team
consumes to move money, the event ID **is** the consumer's dedup key — at-least-once
delivery gives them nothing else to key on. It must be deterministic and derivable by
the consumer (e.g. `<event_type>:<aggregate_id>`), never a fresh `uuid.New()` per emit,
or a redelivery looks like a second, distinct event and the money moves twice.
**Ask for every cross-service event: what does the consumer dedup on?** Verifying
exactly-once *inside your own transaction* answers nothing about the far side of the
outbox. Worked example: `internal/booking/service/cancel.go:196` emits
`booking.refund_requested` with `ID: uuid.New().String()`; Payments consumes it to
issue the refund, so every redelivery is a fresh ID → duplicate refund. Required:
`ID: fmt.Sprintf("booking.refund_requested:%s", bookingID)`.

## U4 — Security / compliance gates must fail CLOSED
**Principle:** when auth, signature (HMAC), SCA/3DS, or a policy check can't run, the
safe default is DENY, never "fall through".
**Smell:** empty/missing config silently disables the gate; an unauthenticated endpoint
that mutates state; a verification branch skipped when a secret is empty; `catch` that
turns a failed check into success.
**Required:** fail closed + startup validation that blocks boot in prod if the gate's
config is absent; unauthenticated state-mutating webhook/callback = **P0**.

## U5 — Reachability: defined ≠ wired
**Principle:** new code that is never registered/called silently no-ops — a whole
acceptance criterion can look "done" while being dead.
**Smell:** a new worker/job/handler/subscriber/route/widget/provider with **no call
site** in the composition root (`wire.go`, `main.go`, DI module, router table, parent
widget). 
**Required:** grep for a reference in the wiring layer. None found → **P0/P1**,
cross-checked against the MR's stated ACs ("AC-3 expiry job is dead code").

## U6 — Spec / AC match
**Principle:** the review's job is "does the code do what the ticket asked", not only
"is the code clean". This is the single largest category real reviewers flag.
**Smell:** MR description / linked ticket says X ("sorts by timestamp", "charges on
accept"); the diff doesn't implement X, or implements a different path.
**Required:** fetch the MR description + linked ticket ACs; for each AC, point at the
code that satisfies it, or flag the gap. A test that asserts a *retired* path is a
spec regression → **P0**.

## U7 — Test-effectiveness (green ≠ proven)
**Principle:** a passing test that never exercises the AC gives false confidence.
**Smell:** unconditional/`t.Skip`/`return` guard; a no-op fake that makes assertions
trivially pass; a test that takes a fallback/decline branch when an env var/key is
missing yet still reports green; tautological asserts; asserts on an unreachable path.
**Required:** the test must fail if the behavior regresses. Flag skips-on-shared-state,
"passes with no key", and coverage that doesn't touch the changed code path.

## U8 — Stale docs / comments / names after a rename
**Principle:** a comment, log string, or assert message that names a symbol/event that
no longer exists is load-bearing misinformation — it sends the next maintainer to dead
code. Distinct from dead code: the text is live, just wrong.
**Smell:** comment/string references an event/type/field the diff (or a prior MR)
renamed or retired; a field name that means the opposite of its wire mapping
(`type` reads JSON `category`); money named as percent; a bool encoded as a sentinel.
**Required:** grep the referenced identifier — zero hits in non-test source = stale.
Fix the reference or the misleading name.

## U9 — Verify at HEAD; don't trust flags
**Principle:** cached platform state lies. Judge from current code, not markers.
**Rules:**
- A thread marked `resolved=true` (or a dev "fixed") counts **only** if the code at
  HEAD proves it — re-read the file at the head SHA, don't trust the flag.
- Merge-conflict status: GitLab `has_conflicts`/`merge_status` and GitHub `mergeable`
  are **lazily computed and can be stale**. When not clearly clean, verify locally:
  `git fetch origin <target>; git merge-tree $(git merge-base HEAD origin/<target>) HEAD origin/<target>`
  and grep for `<<<<<<<`. A conflicting PR is **never** approved (P1 blocker).
- A fix may live in a **stacked MR** (target branch = another open MR's source) — check
  before re-asserting a finding as unaddressed.

## U10 — CI parity (owned by Reviewer D, stated here as principle)
**Principle:** the review must run what the repo's CI runs, not a generic build. A green
generic build while the real pipeline is red is a false pass.
**Smell:** reviewing without reading `.gitlab-ci.yml` / `.github/workflows/*`; skipping
formatter/linter gates (`gofmt -l`, `eslint`, `dart format --set-exit-if-changed`);
building without the build tags the tests need (`//go:build e2e`); trusting a lockfile
resolves when a `path:`/local dependency is committed.
**Required:** mirror the pipeline's exact lint/test/build commands. See Reviewer D in
`personas.md`.

## U11 — Complexity thresholds (measured, not opinion)
Prefer the repo's own linter thresholds; cite the measured value vs the threshold so
it's a FACT. Read first: Dart→`analysis_options.yaml` (DCM), JS/TS→`.eslintrc*`
(`complexity`,`max-depth`), Go→`.golangci.yml` (`gocyclo`/`cyclop`,`nestif`),
Python→`setup.cfg`/`.flake8` (`max-complexity`). Defaults when none: cyclomatic
> 15–20 → P1 (count decision points, state the number); control-flow nesting > 4–5 →
flag (flatten with guard clauses); UI-component nesting > 10 (frontend only) → extract.
Don't flag code under threshold just because it looks busy.

## U12 — Resource lifecycle & data-shape migrations
**Principle:** things that are opened must close; persisted shapes that change must stay
backward-compatible with already-stored data.
**Smell:** temp files/streams/subscriptions/timers created without a `finally`/dispose;
`catch(_)` that wipes persisted state with no log; making a cached model field required
(silent data loss on app upgrade); buffering full media in memory.
**Required:** guaranteed cleanup; a migration/compat path for persisted schema changes;
stream large payloads instead of buffering.

## U13 — Sibling parity (the new thing vs its established neighbors)
**Principle:** a codebase already encodes its contract in the siblings. Any new
endpoint / worker / handler / subscriber / provider must be compared against the
**nearest existing sibling of the same class in the same file or package**, and every
divergence is either justified or a finding. The diff alone can look correct while
silently omitting what every neighbor does.
**Smell:** the new thing differs from its siblings on any of — required headers (e.g.
`Idempotency-Key`), auth/principal enforcement, error→status mapping,
registration/lifecycle, timeout/retry policy, logging/metrics.
**Required:** find the sibling, diff the two by hand, justify or flag each divergence.
**Evidence rule:** a U13 finding **must cite the sibling's `file:line` alongside the new
code's** — "X does it, this doesn't" is the whole shape of the finding. Without the
sibling citation it is an opinion, not a U13.
**Worked example:** `internal/booking/adapter/handler/booking.go:283-285` — the new
cancel POST requires no `Idempotency-Key`, while the sibling money-mutating POSTs in the
same file do. Reviewed against CLAUDE.md, never against its neighbors → missed.

## U14 — Lifecycle: started ≠ drained  *(extension of U5)*
**Principle:** U5 asks *is it wired?*; U14 asks *is it stopped correctly?* A background
task that starts but is never joined loses in-flight work on every deploy.
**Smell:** the diff adds a goroutine / worker / subscriber / ticker / pool, and the
composition root starts it **without** the join its siblings get — a bare
`go X.Run(ctx)` next to `wg.Add(1)`-tracked workers; no context cancellation; an
unbounded drain that can outlive the SIGKILL budget.
**Required:** for every background task the diff introduces, **read the composition
root's shutdown path in full — not a grep for the call site** — and verify it is (a)
joined on shutdown the way its siblings are (WaitGroup/errgroup), (b) context-cancelled,
(c) drain-bounded. **The rule that catches this: the composition root must be read
whenever the diff adds a background task, even when that file is not in the diff.**
A grep that answers "yes, it's wired" and stops is exactly how this is missed.
**Worked example:** `cmd/server/main.go:85-88` starts `SCAExpiryWorker` under
`workerWg.Add(1)` / `defer workerWg.Done()` with `:118` `workerWg.Wait()`; `:105-106`
starts the new reconciler as a bare `go container.Reconciler.Run(reconcilerCtx)` —
never joined. The asymmetry sits ~20 lines apart in one file that was **not in the
diff**; the diff gave pre-existing unchanged code a new responsibility.

---

**Applying these:** each persona (`personas.md`) owns a subset — A: U2, U5, U6, U8,
U13, U3's cross-service consumer contract; B: U1, U3, U4, U7, U9, U12; C: U8, U11;
D: U10 + U5's grep + U14. But any reviewer may raise any lens if the evidence is
theirs. The stack pack tells you what U1–U14 *look like* in this repo's language.

**Scope note (U13/U14):** findings are **not limited to changed files**. Unchanged code
whose contract or risk *this diff changes* is in scope — the composition root, the
siblings, and the consumer on the far side of an event. The panel's failure mode is
anchoring on changed lines; review the blast radius, not just the diff.
