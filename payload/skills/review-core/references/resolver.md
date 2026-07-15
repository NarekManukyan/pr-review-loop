# Stack resolver — pick the lens packs to load

Run this ONCE at the start of a review, before spawning the panel. Output: the list of
lens files under `lenses/` to inject into every persona prompt. Composition is
**base + overlays**: a repo has one base stack and zero-or-more library overlays; load
all that match. On no match, fall back to **universal-only** (personas + universal
lenses + the repo's own CLAUDE.md/ADRs/linter — still a real review).

## Step 1 — detect the base stack from the manifest (repo root)

| Manifest present | Base stack | Base lens |
|---|---|---|
| `pubspec.yaml` | Flutter/Dart | `_base-flutter.md` |
| `go.mod` | Go | `go-postgres.md`¹ |
| `package.json` | JS/TS | (decide by deps, Step 2) |
| `pyproject.toml` / `requirements.txt` / `setup.cfg` | Python | `python.md` (stub) |
| `*.csproj` / `pom.xml` / `build.gradle*` / `Cargo.toml` / `Gemfile` / `composer.json` | .NET / JVM / Rust / Ruby / PHP | no pack yet → **universal-only** |

¹ `go-postgres` assumes Postgres/pgx/sqlc + Pub/Sub, matching this org's backends. If a
Go repo clearly uses neither DB nor a queue (a pure CLI/lib), still load it — its
concurrency/context/error rules are generic Go; skip the SQL sections.

## Step 2 — sub-classify by dependencies (the overlays)

Read the manifest's dependency list and add every overlay that matches.

**Flutter (`pubspec.yaml` dependencies):**
| Dependency seen | Overlay |
|---|---|
| `flutter_bloc` / `bloc` | `flutter-bloc.md` (FULL) |
| `mobx` / `flutter_mobx` | `flutter-mobx.md` (FULL) |
| `flutter_riverpod` / `riverpod` / `hooks_riverpod` | `flutter-riverpod.md` (stub) |
| `provider` | `flutter-provider.md` (stub) |
| `get` (GetX) | (no pack yet — base only) |
> A repo may match several (e.g. `mobx` + `provider`) — load both overlays on top of
> `_base-flutter`. None matched → `_base-flutter` alone.

**JS/TS (`package.json` deps + devDeps):**
| Dependency seen | Pack |
|---|---|
| `@nestjs/core` | `nestjs.md` (FULL) |
| `next` | `react.md` (stub; note SSR) |
| `react` (no `next`) | `react.md` (stub) |
| `@angular/core` | (no pack → universal-only + note) |
| `vue` / `nuxt` | (no pack → universal-only + note) |
| `svelte` | (no pack → universal-only + note) |
| `express` / `fastify` / `koa` (no `@nestjs`) | (no pack → universal-only, apply U1–U12 to the node backend) |

**Go:** `go-postgres.md` already selected; deepen with what's imported — `pgx`/`sqlc`
(SQL sections apply), `cloud.google.com/go/pubsub` or a `river`/outbox pkg (queue
sections apply), `gin`/`chi`/`echo` (HTTP-middleware section applies).

## Step 3 — layer the repo's own rules on top (highest authority)

Always, in this precedence (later overrides earlier when they conflict):
`universal-lenses` → loaded stack pack(s) → repo `CLAUDE.md` + ADRs → repo linter config
(`analysis_options.yaml` / `.eslintrc*` / `.golangci.yml` / `.flake8`) →
`.review-memory/rules.md` + recall. The repo's own docs/config **always win** over a
generic pack (a pack is calibration, never an override).

## Step 4 — announce what loaded

Emit one line the panel and the user can see, e.g.:
`Stack: Flutter · packs: _base-flutter + flutter-mobx + flutter-provider · repo rules: CLAUDE.md, analysis_options.yaml, .review-memory`
or `Stack: unknown (Svelte) · universal-only fallback · repo rules: CLAUDE.md`.
`/review-pr-doctor` prints this for the current repo without running a review.

## Detection cheatsheet (commands)

```bash
# base stack
ls pubspec.yaml go.mod package.json pyproject.toml *.csproj Cargo.toml 2>/dev/null
# flutter state lib
grep -E '^\s*(flutter_bloc|bloc|mobx|flutter_mobx|riverpod|hooks_riverpod|provider|get):' pubspec.yaml
# js/ts framework
node -e "const d={...require('./package.json').dependencies,...require('./package.json').devDependencies};console.log(Object.keys(d).filter(k=>/nestjs|next|react|angular|vue|nuxt|svelte|express|fastify|koa/.test(k)).join(' '))" 2>/dev/null \
  || grep -oE '"(@nestjs/core|next|react|@angular/core|vue|nuxt|svelte|express|fastify|koa)"' package.json
# go libs
grep -oE '(pgx|sqlc|cloud\.google\.com/go/pubsub|gin-gonic|go-chi|labstack/echo|riverqueue)' go.mod go.sum 2>/dev/null | sort -u
```

Detection is best-effort and fast — a missed overlay just means universal + base
coverage, never a crash. When unsure between two overlays, load both.
