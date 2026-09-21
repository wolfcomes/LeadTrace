# LeadTrace Structure Editing Reliability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore reliable Ketcher editing, PDF Structure Source Image capture, and Structure saves without weakening the main LeadTrace security policy.

**Architecture:** Run Ketcher in a same-origin multi-page Vite entry with a narrowly relaxed response policy and a typed `postMessage` bridge. Normalize all PDF region geometry at the shared component boundary. Keep browser tabs synchronized with the authoritative backend session and explicitly recover from CSRF/session drift without replaying mutations.

**Tech Stack:** Vue 3, TypeScript, Pinia, React 18, Ketcher 3.12, Vite 6, Vitest, Vue Test Utils, Playwright Chromium, Nginx, Caddy, pytest.

---

### Task 1: Enforce the PDF bbox precision contract

**Files:**

- Create: `leadtrace/frontend/src/pdf-viewer/geometry.ts`
- Create: `leadtrace/frontend/tests/pdf-region-geometry.spec.ts`
- Modify: `leadtrace/frontend/src/pdf-viewer/PdfReviewCanvas.vue`
- Modify: `leadtrace/frontend/src/pdf-viewer/RegionOverlay.vue`
- Modify: `leadtrace/frontend/tests/structure-source-images.spec.ts`

**Step 1: Write the failing geometry tests**

Add tests that pass the production-derived values
`0.15683718909525357`, `0.22703818369453047`,
`0.6357481626298831`, and `0.7391812865497076` to the desired helper:

```ts
expect(normalizePdfRegionBounds({ x0, y0, x1, y1 })).toEqual({
  x0: 0.1568371891,
  y0: 0.2270381837,
  x1: 0.6357481626,
  y1: 0.7391812865,
});
```

Cover clamping, reversed corners, and a rectangle that collapses after
quantization. Update the Structure Source Image pointer test to mock a real
non-round `getBoundingClientRect()` and assert the serialized request values.

**Step 2: Run the tests to verify RED**

Run:

```bash
cd leadtrace/frontend
npm test -- --run tests/pdf-region-geometry.spec.ts tests/structure-source-images.spec.ts
```

Expected: FAIL because `normalizePdfRegionBounds` does not exist and the current
canvas emits more than ten decimal places.

**Step 3: Implement one shared normalizer**

Define a `PdfRegionBounds` type and a pure helper that:

```ts
const scale = 10 ** 10;
const quantize = (value: number) => Math.round(clamp(value) * scale) / scale;
```

Order the two x and y inputs before quantization. Return `null` unless the
quantized `x1 > x0` and `y1 > y0`. Use the helper in
`PdfReviewCanvas.finishDraw()` and `RegionOverlay.nextBounds()` immediately
before emitting geometry.

**Step 4: Run the tests to verify GREEN**

Run:

```bash
cd leadtrace/frontend
npm test -- --run tests/pdf-region-geometry.spec.ts tests/structure-source-images.spec.ts
```

Expected: both files pass; the POST body contains values with at most ten
decimal places.

**Step 5: Commit**

```bash
git add leadtrace/frontend/src/pdf-viewer leadtrace/frontend/tests/pdf-region-geometry.spec.ts leadtrace/frontend/tests/structure-source-images.spec.ts
git commit -m "fix: normalize PDF region coordinates"
```

### Task 2: Resynchronize cross-tab sessions and CSRF state

**Files:**

- Create: `leadtrace/frontend/src/auth/sessionSync.ts`
- Create: `leadtrace/frontend/tests/session-sync.spec.ts`
- Modify: `leadtrace/frontend/src/auth/store.ts`
- Modify: `leadtrace/frontend/src/api/client.ts`
- Modify: `leadtrace/frontend/src/app/router.ts`
- Modify: `leadtrace/frontend/src/app/AppShell.vue`
- Modify: `leadtrace/frontend/src/i18n/zh-CN.ts`
- Modify: `leadtrace/frontend/tests/auth.spec.ts`
- Modify: `leadtrace/frontend/tests/compound-structure-v2.spec.ts`

**Step 1: Write failing synchronization tests**

Create a testable adapter whose dependencies are `window`, `document`,
`BroadcastChannel`, and storage-like interfaces. Tests must prove:

- an external `credentials-changed` signal calls a forced session refresh;
- focus and transition to `visibilityState === "visible"` refresh the session;
- the signal carries only a versioned event kind, not identity or credentials;
- stopping the adapter removes listeners and closes the channel; and
- the storage fallback works when `BroadcastChannel` is unavailable.

Add store/API tests in which the first Structure PUT returns
`CSRF_VALIDATION_FAILED`, the session endpoint then returns an Admin session,
and no second PUT occurs. Assert that the auth role changes to Admin and a
specific session-change notice is present.

**Step 2: Run the tests to verify RED**

Run:

```bash
cd leadtrace/frontend
npm test -- --run tests/session-sync.spec.ts tests/auth.spec.ts tests/compound-structure-v2.spec.ts
```

Expected: FAIL because forced refresh, synchronization, and the CSRF drift
handler do not exist.

**Step 3: Implement forced refresh and synchronization**

In the store, add:

```ts
refreshSession(options?: { sessionChanged?: boolean }): Promise<void>
startSessionSync(): void
stopSessionSync(): void
dismissSessionNotice(): void
```

Deduplicate concurrent refreshes with one in-flight Promise. A 401 clears the
session; an unavailable response leaves no invented token. Publish a
credential-change event only after login, logout, or password change has
settled. Do not put session data in the event.

In the API client, add a separately registered asynchronous handler for
`CSRF_VALIDATION_FAILED`. Await it before throwing the original `ApiError`, and
never repeat the request. Register the handler and start synchronization from
the router/application bootstrap. Keep the existing 401 routing behavior.

Render `auth.sessionNotice` in `AppShell` as an application-level warning with
a dismiss button. Existing role-derived workspace state must immediately
disable writes after a Reviewer-to-Admin transition.

**Step 4: Run the tests to verify GREEN**

Run:

```bash
cd leadtrace/frontend
npm test -- --run tests/session-sync.spec.ts tests/auth.spec.ts tests/compound-structure-v2.spec.ts
```

Expected: all focused tests pass and the test records exactly one failed PUT.

**Step 5: Commit**

```bash
git add leadtrace/frontend/src/auth leadtrace/frontend/src/api/client.ts leadtrace/frontend/src/app leadtrace/frontend/src/i18n/zh-CN.ts leadtrace/frontend/tests
git commit -m "fix: resynchronize browser session state"
```

### Task 3: Move Ketcher behind an isolated iframe protocol

**Files:**

- Create: `leadtrace/frontend/ketcher.html`
- Create: `leadtrace/frontend/src/ketcher/main.ts`
- Create: `leadtrace/frontend/src/ketcher/styles.css`
- Create: `leadtrace/frontend/src/review/paper/ketcherProtocol.ts`
- Create: `leadtrace/frontend/tests/ketcher-protocol.spec.ts`
- Modify: `leadtrace/frontend/src/review/paper/KetcherEditor.vue`
- Modify: `leadtrace/frontend/tests/ketcher-editor.spec.ts`
- Modify: `leadtrace/frontend/src/styles/components.css`
- Modify: `leadtrace/frontend/vite.config.ts`

**Step 1: Write failing protocol and parent-adapter tests**

Specify discriminated, versioned message types and runtime parsers. Test that
the parent accepts a ready/Molfile message only when both the origin and source
window match. Test that it sends the initial SMILES after readiness, ignores an
echoed Molfile, reports child errors, times out an unresponsive frame, and
removes listeners when disabled or unmounted.

**Step 2: Run the tests to verify RED**

Run:

```bash
cd leadtrace/frontend
npm test -- --run tests/ketcher-protocol.spec.ts tests/ketcher-editor.spec.ts
```

Expected: FAIL because there is no message protocol and the existing component
mounts Ketcher directly in the strict main document.

**Step 3: Implement the protocol and child entry**

Use a fixed protocol marker such as `leadtrace-ketcher-v1`. Keep payloads to
`set-molecule`, `ready`, `molfile`, and `error`. Validate payload shape without
trusting TypeScript at runtime.

The child entry mounts the existing React Ketcher editor with
`StandaloneStructServiceProvider`, imports Ketcher CSS, applies parent molecule
updates serially, and publishes Molfile output on Ketcher change. It accepts
messages only from the same-origin parent and removes handlers on unload.

The Vue component renders:

```html
<iframe src="/ketcher.html" title="Ketcher 化学结构编辑器"></iframe>
```

It keeps the existing props/events/exposed methods and loading/read-only states,
but no longer imports React or Ketcher packages into the main entry. Give the
iframe a stable 480px desktop/420px narrow height without layout shifts.

Configure Vite Rollup input for both `index.html` and `ketcher.html` and confirm
both are emitted by production build.

**Step 4: Run focused tests and production build**

Run:

```bash
cd leadtrace/frontend
npm test -- --run tests/ketcher-protocol.spec.ts tests/ketcher-editor.spec.ts tests/compound-structure-v2.spec.ts
npm run build
test -f dist/index.html
test -f dist/ketcher.html
```

Expected: tests pass, build exits zero, and both HTML entries exist.

**Step 5: Commit**

```bash
git add leadtrace/frontend/ketcher.html leadtrace/frontend/src/ketcher leadtrace/frontend/src/review/paper/KetcherEditor.vue leadtrace/frontend/src/review/paper/ketcherProtocol.ts leadtrace/frontend/src/styles/components.css leadtrace/frontend/tests leadtrace/frontend/vite.config.ts
git commit -m "fix: isolate Ketcher runtime from the main CSP"
```

### Task 4: Scope deployment headers and test real Ketcher under CSP

**Files:**

- Create: `leadtrace/frontend/e2e/ketcher-csp.spec.ts`
- Create: `leadtrace/frontend/e2e/fixtures/ketcher-csp-server.ts`
- Modify: `leadtrace/deploy/nginx/nginx.conf`
- Modify: `leadtrace/deploy/nginx/nginx.native.conf`
- Modify: `leadtrace/deploy/nginx/nginx.native-preflight.conf`
- Modify: `leadtrace/backend/tests/deploy/test_compose_migrations.py`
- Modify: `leadtrace/ops/runbooks/cutover.md`

**Step 1: Write failing deployment and browser tests**

Add pytest assertions over all active Nginx configurations:

- the default response retains `script-src 'self'`, `frame-ancestors 'none'`,
  and `X-Frame-Options DENY`;
- exact path `/ketcher.html` has `script-src 'self' 'unsafe-eval'`,
  `worker-src 'self' blob:`, `frame-ancestors 'self'`, and
  `X-Frame-Options SAMEORIGIN`; and
- no wildcard/static-asset route receives the relaxed policy.

Add a small built-asset fixture server using Node's HTTP APIs. It must send the
strict policy for the test parent and the scoped policy for `ketcher.html`.
The Playwright test loads the real production build, captures CSP console/page
errors, sends `CCO`, waits for Ketcher readiness, and asserts a non-empty Molfile
arrives without CSP violations.

**Step 2: Run tests to verify RED**

Run:

```bash
cd leadtrace/backend
python -m pytest tests/deploy/test_compose_migrations.py -v
cd ../frontend
npm run build
npx playwright test e2e/ketcher-csp.spec.ts --project=chromium
```

Expected: deployment assertions fail because the scoped route is absent; the
browser test fails under the strict inherited policy.

**Step 3: Add exact-path security headers**

For each active Nginx frontend configuration, add an exact
`location = /ketcher.html` that repeats standard security headers, changes only
framing to `SAMEORIGIN`, and applies the approved Ketcher CSP. Proxy the path in
development and use `try_files` in native static deployments.

Update the cutover runbook with an exact Caddy matcher that excludes
`/ketcher.html` from the strict global header block and gives that one response
the approved Ketcher policy. Include `caddy validate` and header checks for both
`/` and `/ketcher.html`. Do not edit or reload the live Caddyfile in this task.

**Step 4: Run tests to verify GREEN**

Run:

```bash
cd leadtrace/backend
python -m pytest tests/deploy/test_compose_migrations.py -v
cd ../frontend
npm run build
npx playwright test e2e/ketcher-csp.spec.ts --project=chromium
```

Expected: pytest passes; Chromium initializes real Ketcher, imports SMILES,
exports Molfile, and logs no CSP violations.

**Step 5: Commit**

```bash
git add leadtrace/deploy/nginx leadtrace/backend/tests/deploy/test_compose_migrations.py leadtrace/frontend/e2e leadtrace/ops/runbooks/cutover.md
git commit -m "fix: scope Ketcher browser permissions"
```

### Task 5: Complete regression verification and review

**Files:**

- Modify only files required by review findings.

**Step 1: Run the complete frontend verification**

Run:

```bash
cd leadtrace/frontend
npm test -- --run
npm run typecheck
npm run build
npx playwright test e2e/ketcher-csp.spec.ts --project=chromium
```

Expected: every command exits zero with no failed tests or CSP errors.

**Step 2: Run backend/static checks**

Run:

```bash
cd leadtrace/backend
python -m pytest tests/deploy/test_compose_migrations.py -v
python -m compileall -q app
cd ../..
git diff --check
git status --short
```

Expected: deployment tests and compilation pass; no whitespace errors; status
contains only intentional changes or is clean after commits.

**Step 3: Request code review**

Review all commits from `fafb2e1` through the branch head against the approved
design. Fix every Critical or Important finding with a failing regression test
where applicable, then rerun the affected and full checks.

**Step 4: Record deployment prerequisites**

Report the exact branch head, build output, test counts, and the fact that the
live Caddy/static release remains unchanged. Deployment must later validate the
candidate Caddyfile before changing the production route and must smoke-test
SMILES save, Ketcher save, and Source Image capture using a controlled Reviewer
session.
