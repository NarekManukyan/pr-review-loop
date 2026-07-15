# react — React / Next.js (STUB)

**Loaded when:** `package.json` deps include `react` (and `next` → note SSR/RSC).
**Composes with:** universal lenses. **Status: stub** — no repos in the current
portfolio; loaded to prove the resolver and give partial coverage. Universal lenses
still fully apply; refine into a FULL pack when React repos appear.

## Idiom rules (top known — extend from evidence)
- **Effect correctness (maps U7/U12):** `useEffect` with a wrong/missing dependency
  array (stale closure or infinite loop); no cleanup return for subscriptions/timers/
  listeners → leak. **P1**.
- **Re-render / memo (maps U11):** new object/array/function literal passed as a prop
  each render defeats `React.memo`/breaks referential equality → wrap in
  `useMemo`/`useCallback`; expensive work in render body. **P2**.
- **Keys (maps U7):** list items keyed by index → reconciliation bugs on reorder. **P2**.
- **State/idempotency (maps U1/U3):** double-submit with no disabled/in-flight guard;
  optimistic update with no rollback. **P1**.
- **Data fetching (maps U4):** auth/authorization enforced only client-side; secrets in
  client bundle; unvalidated form input. **P0/P1**.
- **Next.js:** server vs client component boundary misuse; secrets leaking into a
  `"use client"` module; `getServerSideProps`/route-handler input unvalidated.

## CI gates (for Reviewer D)
`npm ci`, `tsc --noEmit`/`next build`, `eslint`, `prettier --check`, tests.

## Generated / skip
`.next/`, `dist/`, `node_modules/`, `*.d.ts` generated.

## Notes
STUB — promote to FULL from real findings. Until then, universal lenses carry the review.
