# flutter-mobx — MobX store state overlay

**Loaded when:** `pubspec.yaml` deps include `mobx`/`flutter_mobx`.
**Composes with:** `_base-flutter` (owns widget/render/platform) + universal lenses.
Often stacks with `flutter-provider` (stores provided via Provider). This overlay owns
**MobX store idioms** only.

> The most common Flutter state layer in this portfolio (~30 repos). Authored from
> MobX.dart official concepts (verified via context7) applied through the universal
> lenses — no local mined corpus yet, so treat the severities as guidance and cite exact
> code.

## Idiom rules

### Mutations must run inside an action (maps U1/U2; B)
- **An `@action` spans `await`, catch blocks included.** `mobx_codegen` emits an
  `AsyncAction`, whose Zone carries the action context across every continuation —
  the success path, a single-argument `catch (e)`, a two-argument
  `catch (e, stackTrace)`, and a `finally` reached from either. **Verified by
  measurement, not by reading `async_action.dart`.** That file forks the Zone with
  `run` + `runUnary` and has a commented-out `_runBinary` labelled *"invoked for a
  catch clause that has two arguments"* — that comment is a relic of the old
  `Future.then(onError:)` lowering and leads to the wrong conclusion. Modern Dart
  resumes an `await` with a unary continuation and runs the `try`/`catch` inside the
  resumed body.
- **Therefore: never flag a post-await mutation in an `@action` as needing
  `runInAction`, in any branch.** This is the single most common MobX false positive,
  and it survives a plausible-looking source reading — do not re-derive it.
  ```dart
  @action
  Future<void> load() async {
    _isLoading = true;
    try {
      _items = ObservableList.of(await repo.fetch());   // in the action
    } on AppException catch (e, stackTrace) {
      _error = e;                                        // still in the action
    } finally {
      _isLoading = false;                                // still in the action
    }
  }
  ```
- **The real smell:** a write from code with **no action context to inherit** — a
  `Timer` callback, a stream listener, a raw `Future.then(onError:)`, or test code
  mutating an `ObservableList`. Those genuinely assert: the default `writePolicy` is
  `observed` and `enforceWritePolicy` asserts `_state.isWithinBatch` for an atom with
  observers, so the write throws in debug and profile and the observer never sees it.
  **P1** when it is app code on a path the UI reads.
- **A write outside an action does not silently no-op** — under the default policy it
  throws in debug. A finding claiming "the UI just won't rebuild" is the wrong
  diagnosis.
- Clearing state on success/retry (`error = null`) must still happen — a MobX analogue
  of the BLoC copyWith-reset trap: verify a successful retry actually clears the previous
  `error`/`errorKind`. That is about the *write existing*, not about wrapping it.

### Reactions must be disposed (maps U12; B) — leak class
- **Smell:** `autorun`/`reaction`/`when` created in a store or widget whose returned
  `ReactionDisposer` is never called. In a widget: created in `initState`/build with no
  `dispose()`; in a store: no `dispose()` method cancelling them. → memory leak + stale
  side-effects firing after the screen is gone. **P1**.
- **Required:** store every `ReactionDisposer` and call it in the store's `dispose()` /
  the widget's `dispose()`. Confirm the store's `dispose()` is actually invoked (Provider
  `dispose:`/`Disposer`).

### `Observer` actually observes (maps U7; C) — silent no-rebuild
- **Smell:** an `Observer(builder: …)` whose builder does **not read** the observable
  (the read happens outside the builder, or the value was captured before), so the
  widget never rebuilds. Or a screen mutating observables with **no** `Observer`/
  `flutter_mobx` wrapper around the reading widget. **P1** (UI silently stale).
- **Passing collections down:** when handing an `ObservableList` to a child, pass
  `list.toList()` inside the `Observer` builder so the parent `Observer` tracks
  mutations; otherwise child updates are missed. **P2**.

### Derived values are `@computed`, not methods (maps U11; C)
- **Smell:** a getter doing real derivation called from many `Observer`s as a plain
  method → recomputed every read, not cached/tracked. **P2**.
- **Required:** `@computed String get total => …` — cached, invalidated only when its
  observables change.

### Collections & observability (maps U7; B)
- Mutable `List`/`Map`/`Set` fields that should be reactive must be `ObservableList`/
  `ObservableMap`/`ObservableSet` (or reassigned via `ObservableList.of(...)`), else
  `.add()`/`.remove()` won't notify. A plain `@observable List` reassigned wholesale is
  fine; mutated in place is not. **P1**.
- Exposing the raw `ObservableList` and mutating it from the UI layer bypasses the
  store's actions — expose read-only + action methods.

### Store lifecycle & DI (maps U5; A)
- A store constructed directly in a widget (not injected/provided) or a `getIt<Store>()`
  in build (see `_base-flutter` DI rule). A store registered but never provided to the
  subtree that reads it → observers never fire (reachability, U5).

## CI gates (for Reviewer D)
Inherits `_base-flutter`. MobX uses `build_runner` for `*.g.dart` store code — run
`dart run build_runner build -d` before `dart analyze` if the `.g.dart` are gitignored.

## Generated / skip
Inherits `_base-flutter`; MobX store codegen is `*.g.dart` (already skipped).

## Notes
- Do **not** grep async `@action`s for post-await mutations "missing" `runInAction` —
  that check produces only false positives (see the action rule above). The
  highest-yield real checks here are undisposed reactions and `Observer` builders that
  do not read the observable they are supposed to track.
- If the repo also uses `provider`, load `flutter-provider` too (store scoping/`dispose`
  overlaps).
