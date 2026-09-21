# LeadTrace Structure Editing Reliability Design

**Date:** 2026-09-18

**Status:** Approved

## Problem statement

Three production failures currently block the Reviewer structure workflow:

1. Ketcher loads JavaScript chunks but cannot initialize because the production
   Content Security Policy (CSP) rejects dynamic JavaScript evaluation,
   WebAssembly compilation, and Blob Workers used by Ketcher standalone 3.12.
2. A PDF pointer selection produces normalized floating-point coordinates with
   more than ten decimal places, while the API schema accepts at most ten. The
   resulting Structure Source Image request fails validation with HTTP 422.
3. Authentication state is held in each tab, while the session cookie is shared
   by all tabs. Logging in as a different user in another tab replaces the
   cookie but leaves the first tab's role and CSRF token stale. Its next write is
   correctly rejected with `CSRF_VALIDATION_FAILED`, but the page still appears
   editable and reports only a generic save failure.

The fix must preserve the application's strict default CSP, the backend's
decimal contract, and the rule that a rejected mutation is never replayed under
a possibly different identity.

## Considered approaches

### 1. Isolated same-origin Ketcher document (selected)

Build Ketcher as a separate same-origin HTML entry, embed it in the Vue
workspace through an iframe, and exchange only typed structure messages with
the parent. Apply the relaxed CSP and same-origin framing permission only to the
Ketcher document. This is a larger change than altering one header, but it keeps
dynamic evaluation and Blob Worker permission outside the main application
document.

### 2. Relax the CSP for the complete application

Add `unsafe-eval` and `worker-src blob:` to the site-wide policy. This is the
smallest operational change, but it weakens every application route and every
script loaded by the main document. It was rejected because the Ketcher runtime
is the only component that needs these permissions.

### 3. Patch or replace the Ketcher runtime

Investigate a binary-WASM distribution, remove dynamic `Function` construction,
and rebuild the worker integration. This may eventually remove the relaxed
policy, but it couples LeadTrace to an internal Ketcher build and does not
provide a proportionate short-term repair.

The user approved approach 1 on 2026-09-18.

## Architecture

### Ketcher isolation boundary

Vite will produce two HTML entries:

- `index.html` remains the LeadTrace Vue application and retains the strict
  default CSP.
- `ketcher.html` mounts only React, Ketcher, and the standalone structure
  service. It does not initialize Pinia, Vue Router, or any LeadTrace API client.

`KetcherEditor.vue` becomes the parent-side iframe adapter. A shared protocol
module defines and validates a small set of versioned messages:

- parent to child: initialize or replace the current molecule;
- child to parent: ready, current Molfile, or a user-facing error;
- optional request identifiers keep asynchronous replies from overwriting newer
  input.

Both sides require `event.origin === window.location.origin`. The parent also
requires `event.source === iframe.contentWindow`; the child requires
`event.source === window.parent`. Unknown message kinds, protocol versions, and
malformed payloads are ignored. No authentication token, workspace identifier,
or API response crosses this boundary.

The parent keeps the current Vue contract: it accepts `modelValue`, emits
`update:modelValue` with a Molfile, emits `error`, respects read-only mode, and
exposes structure get/set methods. Disabling or unmounting the editor removes
listeners and the iframe. A bounded initialization timeout changes the loading
state into an actionable error instead of leaving an indefinite spinner.

The Ketcher document receives a route-specific policy that permits only what
the bundled standalone runtime requires:

```text
default-src 'self';
connect-src 'self' blob:;
img-src 'self' data: blob:;
style-src 'self' 'unsafe-inline';
script-src 'self' 'unsafe-eval';
worker-src 'self' blob:;
font-src 'self' data:;
object-src 'none';
base-uri 'none';
frame-ancestors 'self';
form-action 'none'
```

The Ketcher response uses `X-Frame-Options: SAMEORIGIN`; all normal application
responses retain `X-Frame-Options: DENY` and `script-src 'self'`. Tracked Nginx
configurations will define the path-specific response. The production Caddy
configuration must apply the equivalent exact-path rule during deployment.

### PDF region normalization

A shared pure geometry function will clamp coordinates to `[0, 1]`, order the
corners, round each value to ten decimal places, and reject a rectangle with no
positive area after quantization. `PdfReviewCanvas` uses it before emitting a
new selection. `RegionOverlay` uses the same function before emitting a move or
resize.

Because Structure Source Images and Evidence both consume these shared PDF
components, the correction covers both write paths. The backend decimal schema
remains unchanged and continues to reject clients that violate its contract.

### Cross-tab session synchronization

The auth store will separate one-time initialization from a forced session
refresh. A small browser synchronization adapter will:

- broadcast a credential-change signal after login, logout, or password change;
- refresh `/api/v1/auth/session` when another tab sends that signal;
- refresh when a tab becomes visible or regains focus;
- use `BroadcastChannel` when available and a `storage` event fallback where it
  is not; and
- deduplicate concurrent refreshes.

Signals contain no usernames, roles, session IDs, or CSRF tokens. Receiving a
signal always obtains authoritative state from the backend rather than trusting
message contents.

The API client will recognize `CSRF_VALIDATION_FAILED` separately from an
ordinary permission error and invoke a registered session-drift handler. The
handler force-refreshes the session and displays a persistent application-level
notice that the active login changed. The original mutation still rejects. It
is never retried automatically, so a write cannot silently execute under the
new identity.

If the refreshed identity is an Admin, `PaperWorkspacePage` immediately becomes
read-only through its existing role-derived `readOnly` state. If the session is
gone, protected navigation returns to Login. A Reviewer may save again only
after the refreshed state is visible and still permits editing.

## Error handling

- Ketcher load, molecule import, and Molfile export failures are returned by the
  iframe protocol and displayed in the existing structure editor alert.
- A missing or unresponsive iframe reports a load error after a bounded timeout.
- Invalid PDF geometry is not submitted; valid geometry is guaranteed to fit
  the backend's ten-decimal contract.
- A CSRF/session drift response shows a specific session-change message. The
  local editor may retain unsaved input, but controls reflect the refreshed
  role and no mutation is replayed.
- A transient session refresh failure does not invent a role or token. Existing
  API error handling remains in force, and the next focus or visibility event
  can refresh again.

## Testing

Implementation follows red-green-refactor for each failure:

1. Add geometry tests using actual long floating-point ratios and assert that
   Structure Source Image and Evidence payloads contain no more than ten decimal
   places.
2. Add auth-store tests with two synchronization clients, a shared simulated
   cookie/session source, focus/visibility refresh, and a
   `CSRF_VALIDATION_FAILED` response. Assert that no write is replayed and an
   Admin transition makes the workspace read-only.
3. Replace the mocked in-document Ketcher test with protocol tests for the
   parent and child. Add a Chromium test against built assets with strict parent
   CSP and the scoped Ketcher CSP, using the real Ketcher standalone runtime to
   import a SMILES value and export a non-empty Molfile.
4. Add static deployment tests proving that only `ketcher.html` receives the
   relaxed script/worker policy and same-origin framing permission.
5. Run the complete frontend unit suite, type checking, production build,
   focused Playwright CSP test, relevant backend/deployment tests, and repository
   whitespace checks.

## Deployment boundary

This change produces code, built assets, tested proxy configuration, and an
explicit production-Caddy patch procedure. It does not modify the live release,
database, session store, or running services during implementation. Deployment
requires a separately verified release build, Caddy validation, an atomic
static-release switch, and post-deployment browser smoke tests.
