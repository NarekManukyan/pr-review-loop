# Lens packs — contract & how to add one

A lens pack is **idioms only** — the concrete, syntax-level form of the universal
principles (`../universal-lenses.md`) in one stack. It never restates a universal
principle; it says "here's what U1/U3/U5 look like in this language, and here are the
stack-specific gates." The resolver (`../resolver.md`) loads packs on demand.

## File naming
- Base stack: `_base-<stack>.md` (leading underscore — always loaded for that stack).
- Library/state overlay: `<stack>-<lib>.md` (e.g. `flutter-mobx.md`, `flutter-bloc.md`).
- Single-file stack (framework == stack): `<name>.md` (e.g. `nestjs.md`, `go-postgres.md`).

## Required sections (keep this order)
```md
# <pack name> — <one line>
**Loaded when:** <resolver condition, e.g. "pubspec.yaml deps include mobx">
**Composes with:** <base + sibling overlays it stacks on>

## Idiom rules
Table or list. Each row: **principle it maps to (U#)** · **smell (grep-able)** ·
**required end state** · severity default. Concrete to the stack's syntax.

## CI gates (for Reviewer D)
The exact lint/test/build commands this stack's CI runs — formatter, analyzer, tags,
codegen — so Reviewer D mirrors the pipeline (universal lens U10).

## Generated / skip
Glob patterns of generated files to skip for this stack (append to the global list).

## Notes
Anything a reviewer must know (domain invariants, common false positives to avoid).
```

## Rules of thumb
- **Evidence over theory.** A "FULL" pack is written from real findings (mined review
  corpus). A "stub" pack lists the top few known idioms + a TODO, and is honest that
  it's shallow — the resolver still loads it, universal lenses still apply.
- **No overlap with universal.** If a rule is true in every language, it belongs in
  `universal-lenses.md`, not here. Here = the stack-specific *shape*.
- **Cite, don't lecture.** Each rule states the smell + the fix in one or two lines; a
  reviewer applies it against exact code.
- **Stubs must not block.** A stub file loading is never an error; it's partial
  coverage on top of full universal coverage.

## Current packs
| File | Status | Loaded when |
|---|---|---|
| `_base-flutter.md` | FULL | `pubspec.yaml` present |
| `flutter-bloc.md` | FULL | pubspec deps include `flutter_bloc`/`bloc` |
| `flutter-mobx.md` | FULL | pubspec deps include `mobx`/`flutter_mobx` |
| `go-postgres.md` | FULL | `go.mod` present |
| `nestjs.md` | FULL | package deps include `@nestjs/core` |
| `flutter-riverpod.md` | stub | pubspec deps include `riverpod` |
| `flutter-provider.md` | stub | pubspec deps include `provider` |
| `react.md` | stub | package deps include `react`/`next` |
| `python.md` | stub | `pyproject.toml`/`requirements.txt` present |
