# flutter-riverpod — Riverpod overlay (STUB)

**Loaded when:** `pubspec.yaml` deps include `riverpod`/`flutter_riverpod`/`hooks_riverpod`.
**Composes with:** `_base-flutter` + universal lenses. **Status: stub.**

## Idiom rules (top known)
- **autoDispose / leaks (maps U12):** long-lived providers holding subscriptions/
  controllers without `autoDispose` or `ref.onDispose(...)` → leak; `keepAlive` misuse.
  **P1**.
- **ref after dispose (maps U12):** using `ref` after the widget/provider is disposed
  (post-await); read `ref.mounted`. **P1**.
- **watch vs read (maps U7/U11):** `ref.read` inside build where `ref.watch` is needed
  (stale UI), or `ref.watch` in a callback causing rebuild churn. **P1/P2**.
- **Provider reachability (maps U5):** a provider never watched/read anywhere → dead;
  a `ProviderScope` missing at root. **P1/P2**.
- **State reset (maps U7):** derived error/loading state that never clears on retry
  (AsyncValue handling); mutating state outside a notifier method.

## CI gates (for Reviewer D)
Inherits `_base-flutter` (riverpod_generator codegen → `build_runner` before analyze).

## Notes
STUB — promote from evidence.
