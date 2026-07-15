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

### Mutations must run inside an action (maps U1/U2; B) — the #1 MobX trap
- **Smell:** an `@observable` mutated **outside** an `@action`/`runInAction` — most
  often **after an `await`** inside an async action. In MobX the action boundary ends at
  the first `await`, so post-await mutations are un-batched (and throw under
  `enforceActions`/strict `ReactiveConfig`). **P1**.
- **Required:** wrap post-await mutations in `runInAction(() { … })` (or split into a
  synchronous `@action`). e.g.
  ```dart
  @action
  Future<void> load() async {
    isLoading = true;                     // ok — before await
    final data = await repo.fetch();
    runInAction(() {                      // required — after await
      items = ObservableList.of(data);
      isLoading = false;
      error = null;                       // clear stale error on success
    });
  }
  ```
- Clearing state on success/retry (`error = null`) must happen in an action too — a
  MobX analogue of the BLoC copyWith-reset trap: verify a successful retry actually
  clears the previous `error`/`errorKind`.

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
- Grep async `@action`s for a mutation after `await` not inside `runInAction` — the
  highest-yield MobX check.
- If the repo also uses `provider`, load `flutter-provider` too (store scoping/`dispose`
  overlaps).
