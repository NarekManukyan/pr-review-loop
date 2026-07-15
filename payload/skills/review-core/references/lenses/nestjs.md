# nestjs — NestJS / TypeScript backend

**Loaded when:** `package.json` deps include `@nestjs/core`.
**Composes with:** universal lenses. Deepen the ORM sections when `typeorm`/`prisma`/
`@mikro-orm` present; the queue sections when `@nestjs/bull`/`bullmq`/`kafkajs`/
`amqplib` present.

> Authored from NestJS framework best-practices (no local mined corpus — this org runs
> ~9 Nest services). Cite exact code; most rules are statically provable.

## Idiom rules

### DI / module wiring (maps U5 reachability; A)
- **Smell:** a new `@Injectable()` provider or `@Controller()` not registered in a
  module's `providers`/`controllers` (and `exports` if used by another module) → runtime
  "Nest can't resolve dependencies of …", or the controller's routes simply don't exist.
  A `forwardRef`/circular dep left unresolved. **P0/P1** — grep the module files.
- **Provider scope:** the default provider is a **singleton** — storing per-request
  state in a service instance field leaks across requests (data bleed between users).
  Use `Scope.REQUEST` or pass state explicitly. **P1**.

### Guards / auth fail-closed (maps U4; A/B)
- **Smell:** a state-mutating route with no `@UseGuards(AuthGuard)`/global guard; a
  `canActivate` that returns `true` (allow) on a thrown error or a missing token; "public
  by default" instead of "authenticated by default + explicit `@Public()`". **P0**.
- **Required:** default to a global auth guard; opt **out** explicitly per public route.
  A guard error must deny, not allow.

### DTO validation & mass-assignment (maps U4/U7; B)
- **Smell:** global `ValidationPipe` without `{whitelist:true, forbidNonWhitelisted:true,
  transform:true}`; a DTO without `class-validator` decorators; binding
  `@Body()` straight to an entity. → mass-assignment / unvalidated input. **P1**.
- **Required:** whitelisted, decorated DTOs; transform on; explicit field allow-list on
  writes.

### Transactions / write+event atomicity (maps U2; A)
- **Smell:** multiple repository writes, or a write followed by `eventEmitter.emit`/
  queue enqueue, not wrapped in a single `dataSource.transaction(...)` /
  `queryRunner` / Prisma `$transaction`. Row persisted but event/side-effect lost on
  failure. **P1**.
- **Required:** one transaction per business action; emit domain events via an outbox or
  inside the tx boundary.

### Concurrency (maps U1; B)
- **Smell:** `findOne` then `save`/`update` with no lock or version → lost update /
  double-spend. **P1**.
- **Required:** guarded `UPDATE … WHERE <precondition>` and check affected rows;
  or TypeORM pessimistic lock (`setLock('pessimistic_write')` inside a tx) / optimistic
  `@VersionColumn`.

### Idempotency (maps U3; B)
- POST create / payment endpoints with no idempotency key → duplicate on client retry.
  Key must be stable and checked before the effect. **P0/P1**.

### Config fail-closed (maps U4; A)
- `ConfigModule` without a validation schema (`Joi`/`class-validator`), or a secret read
  with a silent default when unset → the service boots with a disabled gate. **P1**.
  Validate required env at boot; fail to start in prod if absent.

### Async / error handling (maps U7/U12; B)
- Un-awaited promises (fire-and-forget writes), `async` handlers whose rejections are
  unhandled, `catch` that swallows and returns success, exception filters that leak
  stack traces/internal errors to the client. RxJS subscriptions in a provider not torn
  down (`OnModuleDestroy`). **P1/P2**.

### Query performance (maps U11; C)
- N+1 from lazy relations / missing `relations`/`leftJoinAndSelect`; unbounded
  `find()` with no `take`/pagination; a query that ignores an index. **P2/P1**.

## CI gates (for Reviewer D)
Mirror `.github/workflows` / `.gitlab-ci.yml`. Typical Nest pipeline:
- **`npm ci`** (not `npm install`) — respects the lockfile; a committed local/`file:`
  dep or a lockfile mismatch fails CI.
- **`tsc --noEmit`** or `nest build` — type errors.
- **`eslint .`** and **`prettier --check .`** (or `npm run lint`/`format:check`) — the
  formatter/lint gate blocks merge.
- **`jest`** / `test:e2e` if the pipeline runs them; migrations applied against a
  throwaway DB if CI does.

## Generated / skip
`dist/`, `node_modules/`, `*.spec.ts` snapshots, `coverage/`, generated Prisma client
(`@prisma/client`), `migrations/*` are reviewed (not skipped).

## Notes
- Reachability (U5) is the highest-value Nest check — the module system makes
  "defined but not registered" both common and statically detectable.
- This is a FULL-intent pack but from best-practices, not mined findings — refine with
  real corpus once Nest reviews accumulate in `.review-memory`.
