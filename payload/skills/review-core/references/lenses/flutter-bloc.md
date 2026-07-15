# flutter-bloc — BLoC/Cubit state overlay

**Loaded when:** `pubspec.yaml` deps include `flutter_bloc`/`bloc`.
**Composes with:** `_base-flutter` (owns widget/render/platform) + universal lenses.
This overlay owns **state-shape & bloc-lifecycle idioms** only.

> Authored from the dz44 mobile corpus (minitok_clean, food-delivery, bookings,
> notification, explorer, referral — all BLoC).

## Idiom rules

### `copyWith` nullable-reset (maps U7/U12; B) — highest raw frequency
- **Smell:** a freezed/BLoC state `copyWith` field written `x: x ?? this.x`, where some
  call site needs to **clear** it (`copyWith(error: null)` on load/success). `?? this.x`
  makes an explicit `null` mean "keep", so the field can **never** be reset → a stale
  `error`/`errorKind` survives a successful retry. **P1**.
- **Required:** use freezed's generated `copyWith` (which distinguishes "not passed"
  from `null`), or a sentinel / `T? Function()?` wrapper. Check every nullable state
  field against its call sites — if any site clears it, `?? this.x` is a bug.

### Bloc lifecycle & purity (maps U2/U4; A/B)
- **`emit` after close:** an async handler that `emit`s after `await` with no
  `if (isClosed) return;` (or `emit.isDone`) guard → "emit after close" throw. **P1**.
- **No navigation / side-effects in a bloc:** `router.push`/`Navigator` or direct
  platform calls inside a bloc/cubit invert layering → surface via state + a listener.
  **P1** per DI/arch ADR.
- **Subscriptions:** `StreamSubscription`/`Timer` opened in a bloc must be cancelled in
  `close()`; opened in `on<Event>` without an idempotency guard leaks on re-entry. **P1**.
- **Freezed events/states:** events/states should be freezed unions; a non-exhaustive
  `map`/`when`/`switch` over them hides new variants (see `_base-flutter` U-exhaustive).

### Rebuild scoping (maps U11; C)
- `BlocBuilder` with no `buildWhen` on a state that changes for unrelated reasons →
  needless rebuilds; a whole-page `BlocBuilder` where a small `BlocSelector` would do.
  **P2**. Every handler emitting `isLoading: true` (full-screen loader) on a per-item
  action → scope the flag (from `_base-flutter`).

### Error handling in `fold` (maps U7; B)
- `result.fold((_) {}, ...)` that swallows the `Failure`; only one of several results'
  errors propagated (a seller error silently lost while a related error surfaces) →
  every failure branch must surface or be deliberately, visibly handled. **P1/P2**.

## CI gates (for Reviewer D)
Inherits `_base-flutter` CI gates. BLoC apps typically run `build_runner` for freezed —
run codegen before `dart analyze` if `*.freezed.dart`/`*.g.dart` are gitignored.

## Generated / skip
Inherits `_base-flutter` (freezed/g.dart already covered).

## Notes
- `copyWith(error: null)` is the canonical trap — grep state files for `?? this.` on
  fields that any success/load path tries to clear.
