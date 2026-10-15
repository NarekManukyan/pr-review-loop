# _base-flutter — Flutter/Dart, state-management-agnostic

**Loaded when:** `pubspec.yaml` present. Always loaded for Flutter, under whatever
state overlay(s) the resolver adds (`flutter-bloc`, `flutter-mobx`, …).
**Composes with:** universal lenses + the state overlay (which owns state-shape idioms).

> Authored from the mined mobile corpus (minitok_clean, food-delivery-front, tencent,
> notification_center, bookings-front, referral, explorer-front, wallet, …). Covers the
> widget/render/platform/packaging layers common to every Flutter app.

## Idiom rules

### Render-tree validity & responsive layout (maps U-render; C)
- `Positioned`/`Expanded`/`Flexible` must be a **direct** child of `Stack`/`Row`/
  `Column` — wrapping in `Visibility`/`Padding`/`Container` throws a ParentDataWidget
  error at runtime. **P0** (crash).
- Unconstrained `Text` beside a `Positioned`/overlay → overlap; raw numeric
  width/height where the file otherwise uses `.w`/`.h`/`AppDimensions` scaling → breaks
  responsive convention; geometry that assumes portrait (hardcoded system insets,
  `min/max` on screen edges) breaks in landscape. **P1/P2**.

### Design system & i18n (maps U8; C) — sweep exhaustively, always report
This is the highest-frequency category the team's human reviewers leave — **enumerate
every instance with `file:line`, even when the MR also has P0/P1 findings** (do not drop
the sweep for the deep bugs; see personas.md "Reporting completeness").
- Hardcoded dimensions/sizes/radii/spacing (`size: 64`, `EdgeInsets.only(top: 6)`,
  `width: 32`, `BorderRadius.circular(2)`, `SizedBox(height: 42)`, `strokeWidth: 2`) and
  colors (`Color(0x…)`, raw `TextStyle`) in `lib/` bypass the design system → use
  `AppDimensions`/theme/`context.<tokens>`. **P2**. Grep the changed widgets for raw
  numeric literals in `EdgeInsets`/`SizedBox`/`BorderRadius`/`width`/`height` and list
  each — this is exactly what reviewers flag by hand.
- User-facing string literals (`Text('Added to cart')`, toast/log text shown to users)
  not localized → `LocaleKeys.*.tr()`; digits/currency via `NumberFormat` (never a
  hardcoded `$`). **P2** (P1 if the app ships multiple locales — this org: UAE/KSA/RU/EU).

### Reuse before build (maps U11; C) [reuse] — a copy of existing code is a P1
Panels drop this as "style" or "refactor for elegance", and whole features then ship
with private copies of the design system (measured: an 8-PR stack reviewed over 6–16
rounds each got 0 reuse findings and needed a cleanup refactor after merge). It is not
style: a copy drifts, misses the original's fixes, and often misses behaviour (a
hand-built search field has no clear/Cancel). On by default; `--no-reuse` or
`"reuse_check": false` drops this section.
- **The catalog is in your packet:** `reuse-catalog.md` lists what existed at the
  merge-base — design-system widgets, app-wide widgets, core use cases, core
  helpers/extensions and every feature use-case name. Read it with the packet.
- **For every new class or top-level function the diff adds** — private widgets
  (`class _X extends …Widget`), new `*UseCase`s, helpers, mappers, extensions — ask:
  does the catalog, or another feature (grep its distinctive calls/keys), already do
  this job? A new widget that re-builds an existing one (sheet frame vs a sheet-body
  widget, button row vs a modal-actions widget, selectable row, disclosure row, search
  field, calendar, stepper, expandable text, success header, page dots, test-id
  wrapper), a use case that opens/does what an existing one does, or a mapping that
  re-derives a core helper → **P1**, even when users see no difference today. Cite both
  sides: the new code's `file:line` and the existing symbol's path, and name the call
  that replaces it.
- **Copies inside the PR count too:** the same widget/field/mapping written twice in two
  of the PR's own features → **P1**; fix = one shared widget in the owning feature.
- **The fix may touch shared code.** Using an existing design-system widget is never "a
  shared-code change". Adding a small, generic option to it (a test-id or callback
  parameter) is in scope. Only a *new* design-system widget, or a breaking change to
  one, is a follow-up — then report the copy as P2 with the follow-up named.
- **Not a finding:** a near-copy the existing widget genuinely cannot express (say what
  is missing), a one-off layout built from tokens with no equivalent, or overlap with
  code in another open PR.
- One inline thread per instance (P1), not a digest line.

### Permissions & platform (maps U4/U12; B) — the mobile blind spot
- Any gallery/camera/mic/storage/location access must **request the permission** and
  surface a **permission-specific** failure (a denied-permission CTA), not collapse
  every failure into one generic toast. **P1**.
- Platform-only plugins need an explicit iOS/Android split or a documented no-op — a
  download/share action unsupported on iOS must not silently fail. **P1**.
- Native sources under `ios/`/`android/`: observers/listeners/notification-center
  registrations must be removed in `deinit`/`onDestroy` (leak/crash). `flutter analyze`
  cannot see native code — Reviewer D must lint it (SwiftLint/ktlint) or a persona must
  read it. **P1**.
- System-inset/orientation padding must derive from `MediaQuery`, not a hardcoded px.

### DI / mock-in-prod (maps U4/U5; A) — deterministic, high-value
- A `*Mock*`/`*Fake*` class under `lib/` carrying `@injectable` / `@LazySingleton(as:
  <RealInterface>)` **without** an `@Environment('dev')`/`env:` filter or `kDebugMode`
  guard becomes the **default prod binding** — the real datasource never registers,
  real HTTP never happens. **P0/blocker**. Also verify the real impl is registered for
  prod. (Seen in food/wallet/notification.)
- Direct `getIt<X>()` / service-locator calls inside a widget or state object (instead
  of constructor injection) → **P1/P2** per the repo's DI ADR. Count the call sites.

### Money & data typing (maps U8; B)
- Financial values as `String` (e.g. `discount: String?`) violate "money is always
  `double`, never String" → parsing/rounding hazard. **P1**. Render via
  `toStringAsFixed(2)` + locale separators.
- Semantic naming/wire mismatch: a field named `type` that reads JSON `category`; money
  named as percent (`discountAmount` shown as `%`); a count getter that returns unique
  items where the UI wants total units; a bool smuggled through a sentinel `double`
  (`0`/`-1`). **P1** — bug magnet.

### Resource lifecycle & persistence (maps U12; B)
- Temp files created for downloads/exports must be cleaned in a `finally`; buffering a
  whole video/image as `Uint8List` in memory → stream to disk. **P1/P2**.
- `Dio()`/HTTP with no `receiveTimeout`/`CancelToken` can hang a loading dialog
  forever. **P1**.
- Changing a persisted model field to `required`/non-null is a **cache schema break** —
  users silently lose cached state (cart) on app upgrade → provide a migration/compat
  path. `catch (_)` that wipes persisted state must at least log. **P1**.

### Correctness patterns (maps U7; B)
- `initState` async + `setState` without a `mounted` check → crash on fast nav. **P1**.
- Non-exhaustive `switch`/wildcard on an enum/sealed type hides new variants (a new
  `ContentType` silently routes to the wrong screen) → drop the wildcard so the compiler
  flags additions. **P1**.
- Optimistic UI mutation (follow toggle, like) with no rollback on failure and no
  re-entrancy/debounce guard on the tap handler → duplicate network calls / wrong state.
  **P1**. Scope loading flags to the action (no full-screen spinner on a per-item tap).
- Analytics fired regardless of success/failure inflates metrics with failures. **P2**.
- **Tap target enlarged by a transparent box does not enlarge the hit area.**
  `GestureDetector` defaults to `HitTestBehavior.deferToChild`, and
  `SizedBox`/`Center`/`Padding`/`Align` are transparent to hit testing — so
  `GestureDetector(child: SizedBox.square(dimension: 44, child: Center(child:
  Icon(...))))` still only receives taps on the icon glyph. Check third-party tap
  wrappers too (`flutter_scale_tap`'s `ScaleTap` builds a `Listener` + `GestureDetector`
  with no `behavior`). Fix: `behavior: HitTestBehavior.opaque`, or a hit-testable box
  (`ColoredBox`, `Material`). **P1** when the PR's stated goal is tap-target size — the
  fix is then silently ineffective (real miss: mobile_app #238, four sites, shipped).
  Conversely, an opaque full-screen view (`ColoredBox`) stacked over a tap-to-reveal
  overlay swallows the reveal tap. **P2**.
- Async init in a hook/`State` (`useCallback`, `initState`) that awaits, then registers
  the controller with a global handler/service, with no disposed/`mounted` check after
  the await → a disposed controller gets re-registered on fast navigation. **P2**.

### Perf / quality (maps U11; C)
- Real work in `build()` (`NumberFormat(...)`, filtering, parsing, `getIt<Bloc>()..add()`)
  → memoize / move out. Missing `const`. Missing `buildWhen`/selective rebuilds (owned
  more precisely by the state overlay). Dead code (orphaned widgets/usecases/events with
  zero references). ~95% duplicated widgets → extract. Stale `//TODO` / commented-out
  code, TODOs without a ticket ref.

## CI gates (for Reviewer D)
Mirror the repo's CI. Typical Flutter pipeline:
- **`flutter pub get`** on the **pinned** deps — a committed `path:`/local dep
  (`path: ./ui_components`) breaks everyone else's `pub get` even though it resolves for
  the author. **Blocker.**
- **`dart format --output=none --set-exit-if-changed .`** (or `dart format .` gate).
- **`dart analyze`** / `flutter analyze` at the module's **pinned SDK** (an
  `analysis_options.yaml` option needing a newer SDK than pinned fails). Run codegen
  first if generated files are gitignored (`dart run build_runner build -d`).
- Native lint (`ios/`/`android/`) if the pipeline runs it — analyze can't see it.

## Generated / skip
`*.g.dart`, `*.freezed.dart`, `*.gen.dart`, `*.tailor.dart`, `*.config.dart`,
`*.gr.dart`, `*.chopper.dart`, `*.mocks.dart`, `lib/gen/**`, `lib/src/l10n/**`,
`*.pb.dart`, `pubspec.lock`.

## Notes
- pubspec/dependency policy is a Reviewer-D concern too: flag `path:` deps, unpinned git
  deps, cross-repo/feature-package deps, and `pubspec.yaml` version vs an in-code
  version constant drift.
- The state overlay owns `copyWith`/observable/notifier idioms — don't duplicate them
  here.
