# go-postgres — Go backend on Postgres (pgx/sqlc) + Pub/Sub + Gin/chi

**Loaded when:** `go.mod` present. Deepen the SQL sections when `pgx`/`sqlc` imported;
the queue sections when `cloud.google.com/go/pubsub`/`river`/an outbox pkg imported;
the HTTP section when `gin`/`chi`/`echo` imported.
**Composes with:** universal lenses (always). Pure CLI/lib Go → apply concurrency +
error + context rules, skip SQL/queue/HTTP sections.

> Authored from the mined backend corpus (minitok.go, booking-back, explorer-back,
> business-back, shared-go). Center of gravity: concurrency, money-movement,
> transactional integrity. Cite exact code — most of these are provable statically.

## Idiom rules

### Concurrency in SQL (maps U1 — highest-frequency backend finding)
- **Smell:** `SELECT`/`GetX` then a separate `UPDATE`/`Save` with no `FOR UPDATE`; a
  count/limit/budget check outside the tx that later writes; a status transition that
  reads state then updates unconditionally. → **P1** TOCTOU.
- **Required:** encode the precondition in the write — `UPDATE … SET … WHERE id=$1 AND
  <every column the decision depends on> RETURNING …`, then treat `RowsAffected()==0`
  as "lost the race" (sqlc `:execrows`, or `pgx` `CommandTag.RowsAffected()`). Or
  `SELECT … FOR UPDATE` inside the same `RunInTx`. Every decision column must be in the
  CAS `WHERE`. (e.g. `escrow_service.go` budget check ran outside the tx; `booking.sql`
  CAS missed the `sca_status` column.)

### Transactional outbox / write+event atomicity (maps U2)
- **Smell:** `repo.Create(x)` (or any state write) followed by a separate
  `outbox.Store` / `publisher.Publish` / remote HTTP call, not inside one `RunInTx`.
  Row exists but event never published on a crash between them. → **P1**.
- **Required:** the state write and the outbox insert commit in the same transaction; a
  relay publishes from the outbox with at-least-once + idempotent consumers. Name the
  SIGTERM window.

### Idempotency (maps U3)
- **Missing key:** money-movement / booking create with no idempotency key → duplicate
  on client retry. **P0/P1** (org target: "0 duplicated payments/month").
- **Unstable key:** `uuid.New()` generated per call/attempt (e.g. a Stripe/Expedia
  reference) — must derive from a stable row id so retries dedupe. **P1**.
- **Cross-service dedup:** the outbox row's stable `event_id` must ride onto the wire;
  regenerating it per publish attempt breaks downstream dedup. **P1**.

### Fail-closed security & compliance (maps U4)
- **Smell:** empty config silently disables a gate (SCA/3DS bypass when callback URL
  unset); an unauthenticated callback/webhook that mutates state; HMAC verification
  skipped when the secret is empty; a compliance branch that "falls through" to the
  direct path. → **P0**.
- **Required:** fail closed + startup validation blocking prod boot when the gate's
  config is absent; every state-mutating webhook authenticated/signed.

### Ledger / money-conservation invariant (domain, maps U2/U6)
- **Smell:** an `UPDATE … SET balance = balance ± X` **not** accompanied by a balanced
  double-entry journal row; a "single-leg"/"legless" balance that leaves a counterparty
  unbalanced; a seed/cleanup that relocates drift onto a shared account. → **P0/P1**
  (real money; can trip a `kill_all_writes` reconciler).
- **Required:** every credit has a matching debit; `balance == SUM(credit legs) −
  SUM(debit legs)`. If the repo has a ledger/invariants ADR, cite it. Only apply when
  the diff touches wallet/journal/balance code.

### Compensating actions & reconciler completeness (maps U2/U5)
- **Smell:** a failed refund/credit side-effect only logs, with no pending-compensation
  record; a new terminal/resting state (`refund_pending`, `credit_pending`) the
  periodic reconciler/sweeper query doesn't select → stuck money, no safety net. → **P1**.
- **Required:** failed side-effect emits a pending-compensation row; the reconciler
  query is updated to see every new resting state.

### Cross-repo / deploy-order / migration hygiene (maps U5/U6/U8)
- Producer emits an event a not-yet-deployed consumer must handle → the consumer's
  unknown-event "ack and skip" silently drops it (guide "stuck forever"). Gate behind a
  default-off flag or enforce deploy order. **P1**.
- Helm value keys must be backed by a **published** chart template, else a silent no-op
  deploy that still reports success. **P1**.
- New migration number collides with a sibling branch's (`000042` already taken);
  down-migration must `DROP TYPE` and guard `CREATE TYPE … IF NOT EXISTS`; a partial
  index's predicate must match the query's `WHERE` or it seq-scans. **P1/P2**.

### Context & timeouts (maps U12)
- Service methods with no `context.WithTimeout` → unbounded execution. Don't reuse a
  drained `shutdownCtx` for a final flush. Graceful-shutdown budgets that stack to 2×.
  Row locks (`FOR UPDATE SKIP LOCKED`) must not be held across a network `Publish`.

### Pub/Sub / worker semantics (maps U1/U3/U7)
- At-least-once → handlers must be idempotent; **ack** malformed/unknown messages,
  **nack** transient service errors (don't ack-drop a real failure). Claimed outbox
  rows stuck "processing" need a reclaim after N minutes. Unbounded goroutine-per-event
  fan-out → bounded pool / `PublishAsync`. DLQ threshold off-by-one.

### Gin/chi HTTP middleware (maps U4/U5)
- Auth attached **opt-in per route** is a structural risk — a future route ships
  unauthenticated. Prefer a sub-router/group where auth is structural. Health/metrics
  probes exempt from tracing + not counted as 5xx; load-shed 503s are backpressure, not
  server errors (don't log at ERROR / count as faults). Prometheus: monotonic →
  `Counter` + `_total`, not a gauge (an operator can't `rate()` a gauge).

### sqlc / pgx idioms (maps U7/U12)
- Check `RowsAffected` on `:execrows` (phantom update otherwise); query column names
  must match the schema (a wrong column is a compile/runtime break); `:one` +
  `errors.Is(err, sql.ErrNoRows)` (never `==`) → domain error; prefer keyset
  `(created_at,id) < …` over `OFFSET` on hot lists.

### Go error/nil hygiene (maps U12; complements CodeRabbit)
- Wrap errors with context consistently (`fmt.Errorf("...: %w", err)`); no ignored
  errors (`_ = json.Marshal(...)` on a path that can fail); defensive nil-map init in
  exported fluent setters; copy caller-owned maps/slices in constructors; `iterator.Done`
  sentinel via `errors.Is`, not string compare; guard `nil` before deref in exported
  entry points (`PublishAsync(ctx, nil)` must not panic).

## CI gates (for Reviewer D)
Mirror `.gitlab-ci.yml` / `.github/workflows`. This org's Go pipelines gate on:
- **`test -z "$(gofmt -l .)"`** — a single unformatted file fails `lint` and blocks
  merge regardless of review. Run `gofmt -l .`; non-empty → P1.
- **`go vet ./...`** and, when tests use build tags, **`go vet -tags=<tag> ./...`** +
  **`go test -tags=<tag> -run=^$ ./...`** (compile-only). `go build ./...` alone SKIPS
  `_test.go` and `//go:build` files — a test-only MR can be broken while build is green.
- **`golangci-lint run`** if `.golangci.yml` exists (respect its thresholds).
- **`go mod verify`** / tidy check. Migrations: apply against a throwaway Postgres if
  the pipeline does.

## Generated / skip
`*.pb.go`, `*_gen.go`, `*.sql.go` (sqlc), `mock_*.go` / `*_mock.go`, `wire_gen.go`,
`vendor/`, `bin/`.

## Notes
- Reachability (U5) is high-value here: new River/cron workers and Pub/Sub subscribers
  must be registered in `wire.go`/`main.go`/the DI providers — grep for the call site;
  "defined but never spawned" = a dead AC (`SCAExpiryWorker`, `coin_expiration_job`).
- The strongest real P0s combined lenses (unauthenticated SCA callback **+** a CAS race
  → a trivial PSD2 bypass). Chain findings when they compound.
