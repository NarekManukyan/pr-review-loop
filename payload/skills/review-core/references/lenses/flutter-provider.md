# flutter-provider — Provider / ChangeNotifier overlay (STUB)

**Loaded when:** `pubspec.yaml` deps include `provider`.
**Composes with:** `_base-flutter` + universal lenses (and often another state overlay —
Provider is frequently the delivery mechanism for MobX stores or ChangeNotifiers).
**Status: stub** — top idioms only; refine from evidence.

## Idiom rules (top known)
- **notifyListeners after dispose (maps U12):** a `ChangeNotifier` calling
  `notifyListeners()` after `dispose()` (async gap) throws; disposers not wired in the
  `ChangeNotifierProvider`. **P1**.
- **Rebuild scope (maps U11):** `Provider.of<T>(context)` / `context.watch` at a level
  that rebuilds a large subtree where `Selector`/`context.select` would isolate it. **P2**.
- **Provider not above consumer (maps U5):** a `context.read<T>()` with no provider in
  the ancestor tree → `ProviderNotFoundException` at runtime. **P1**.
- **State in build (maps U11):** creating the notifier inside `build` instead of
  `create:` → new instance every rebuild, lost state. **P1**.

## CI gates (for Reviewer D)
Inherits `_base-flutter`.

## Notes
STUB. When paired with MobX, `flutter-mobx` owns the store idioms; this owns Provider
wiring/dispose only.
