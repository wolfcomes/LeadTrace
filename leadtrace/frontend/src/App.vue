<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from "vue";

import { ApiRequestError, fetchReadiness } from "./api/health";


type ViewState = "loading" | "ready" | "unavailable" | "forbidden" | "not-found" | "error";

const state = ref<ViewState>("loading");
let activeRequest: AbortController | undefined;

async function refresh(): Promise<void> {
  activeRequest?.abort();
  activeRequest = new AbortController();
  state.value = "loading";
  try {
    const readiness = await fetchReadiness(activeRequest.signal);
    state.value = readiness.status === "ready" ? "ready" : "unavailable";
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") return;
    if (error instanceof ApiRequestError && error.status === 403) {
      state.value = "forbidden";
    } else if (error instanceof ApiRequestError && error.status === 404) {
      state.value = "not-found";
    } else {
      state.value = "error";
    }
  }
}

onMounted(refresh);
onBeforeUnmount(() => activeRequest?.abort());
</script>

<template>
  <div class="page-shell">
    <header class="masthead">
      <a class="brand" href="/" aria-label="LeadTrace home">
        <span class="brand-mark" aria-hidden="true">LT</span>
        <span>
          <strong>LeadTrace</strong>
          <small>Evidence-led optimization intelligence</small>
        </span>
      </a>
      <span class="environment">Secure LAN workspace</span>
    </header>

    <main class="status-stage" aria-live="polite">
      <section v-if="state === 'loading'" class="status-card" data-state="loading">
        <span class="spinner" aria-hidden="true"></span>
        <p class="eyebrow">System check</p>
        <h1>Connecting to LeadTrace</h1>
        <p>Verifying the database and protected evidence store.</p>
      </section>

      <section v-else-if="state === 'ready'" class="status-card ready" data-state="ready">
        <span class="status-icon" aria-hidden="true">✓</span>
        <p class="eyebrow">All required services available</p>
        <h1>Platform ready</h1>
        <p>The professional review and publication workspace is being assembled.</p>
      </section>

      <section
        v-else-if="state === 'unavailable'"
        class="status-card warning"
        data-state="unavailable"
      >
        <span class="status-icon" aria-hidden="true">!</span>
        <p class="eyebrow">Dependency check failed</p>
        <h1>Temporarily unavailable</h1>
        <p>LeadTrace is running, but a required internal service is not ready.</p>
        <button type="button" @click="refresh">Retry connection</button>
      </section>

      <section v-else-if="state === 'forbidden'" class="status-card" data-state="forbidden">
        <span class="status-icon" aria-hidden="true">403</span>
        <p class="eyebrow">Authorization required</p>
        <h1>Access denied</h1>
        <p>Your account does not have permission to open this resource.</p>
      </section>

      <section v-else-if="state === 'not-found'" class="status-card" data-state="not-found">
        <span class="status-icon" aria-hidden="true">404</span>
        <p class="eyebrow">Resource unavailable</p>
        <h1>Page not found</h1>
        <p>The requested LeadTrace location does not exist.</p>
      </section>

      <section v-else class="status-card" data-state="error">
        <span class="status-icon" aria-hidden="true">×</span>
        <p class="eyebrow">Unexpected response</p>
        <h1>Something went wrong</h1>
        <p>The request could not be completed. No source data was changed.</p>
        <button type="button" @click="refresh">Try again</button>
      </section>
    </main>

    <footer>
      <span>Version 0.1 foundation</span>
      <span>Review • Approve • Publish • Trace</span>
    </footer>
  </div>
</template>

<style scoped>
:global(*) { box-sizing: border-box; }
:global(body) { margin: 0; min-width: 320px; color: #17231f; background: #f3f5f2; }
:global(body), button { font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
.page-shell { min-height: 100vh; display: grid; grid-template-rows: auto 1fr auto; background: radial-gradient(circle at 82% 18%, rgba(183, 150, 75, .13), transparent 28%), #f3f5f2; }
.masthead, footer { display: flex; align-items: center; justify-content: space-between; padding: 24px clamp(24px, 5vw, 72px); }
.masthead { border-bottom: 1px solid #dce2dd; background: rgba(250, 251, 249, .9); backdrop-filter: blur(10px); }
.brand { display: flex; gap: 14px; align-items: center; color: inherit; text-decoration: none; }
.brand-mark { display: grid; place-items: center; width: 44px; height: 44px; border-radius: 12px; color: #f8faf8; background: #173e32; font: 700 14px/1 Georgia, serif; letter-spacing: .08em; }
.brand strong, .brand small { display: block; }
.brand strong { font: 600 20px/1.2 Georgia, serif; letter-spacing: .01em; }
.brand small, .environment, footer { color: #637169; font-size: 12px; letter-spacing: .03em; }
.brand small { margin-top: 3px; }
.environment { padding: 7px 11px; border: 1px solid #cbd5ce; border-radius: 999px; }
.status-stage { display: grid; place-items: center; padding: 48px 24px; }
.status-card { width: min(100%, 620px); padding: clamp(34px, 6vw, 64px); border: 1px solid #d8dfda; border-radius: 24px; background: rgba(255, 255, 255, .92); box-shadow: 0 24px 70px rgba(25, 52, 43, .08); text-align: center; }
.status-card h1 { margin: 8px 0 14px; color: #173e32; font: 500 clamp(30px, 5vw, 48px)/1.08 Georgia, serif; }
.status-card p { max-width: 480px; margin: 0 auto; color: #627069; line-height: 1.65; }
.eyebrow { color: #98762c !important; font-size: 11px; font-weight: 700; letter-spacing: .13em; text-transform: uppercase; }
.status-icon, .spinner { display: grid; place-items: center; width: 54px; height: 54px; margin: 0 auto 24px; border-radius: 50%; color: #fff; background: #173e32; font-weight: 700; }
.warning .status-icon { background: #9b6e22; }
.spinner { border: 2px solid #d5dfd8; border-top-color: #173e32; background: transparent; animation: spin .8s linear infinite; }
button { margin-top: 26px; padding: 11px 18px; border: 0; border-radius: 9px; color: #fff; background: #173e32; font-size: 14px; font-weight: 650; cursor: pointer; }
button:hover { background: #245b49; }
footer { border-top: 1px solid #dce2dd; }
@keyframes spin { to { transform: rotate(360deg); } }
@media (max-width: 620px) { .environment, footer span:last-child { display: none; } }
@media (prefers-reduced-motion: reduce) { .spinner { animation: none; } }
</style>
