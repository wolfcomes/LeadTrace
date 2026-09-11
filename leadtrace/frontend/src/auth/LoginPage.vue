<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";

import { useAuthStore } from "./store";
import { zhCN } from "../i18n/zh-CN";

const auth = useAuthStore();
const route = useRoute();
const router = useRouter();
const username = ref("");
const password = ref("");

async function submit(): Promise<void> {
  const accepted = await auth.login(username.value, password.value);
  password.value = "";
  if (!accepted) return;
  if (auth.user?.must_change_password) {
    await router.replace({ name: "change-password" });
    return;
  }
  const destination = typeof route.query.redirect === "string"
    ? route.query.redirect
    : "/";
  await router.replace(destination.startsWith("/") ? destination : "/");
}
</script>

<template>
  <main class="login-stage">
    <section class="brand-panel" aria-labelledby="platform-name">
      <div class="brand-lockup">
        <span class="brand-mark" aria-hidden="true">LT</span>
        <div>
          <strong id="platform-name">{{ zhCN.brand.name }}</strong>
          <span>{{ zhCN.brand.descriptor }}</span>
        </div>
      </div>
      <div class="brand-message">
        <p class="eyebrow">{{ zhCN.brand.eyebrow }}</p>
        <h1>{{ zhCN.brand.headline }}</h1>
        <p>{{ zhCN.brand.introduction }}</p>
      </div>
      <p class="environment"><span aria-hidden="true"></span>{{ zhCN.brand.environment }}</p>
    </section>

    <section class="form-panel">
      <form class="login-card" novalidate @submit.prevent="submit">
        <p class="eyebrow">{{ zhCN.auth.signInEyebrow }}</p>
        <h2>{{ zhCN.auth.signInTitle }}</h2>
        <p class="description">{{ zhCN.auth.signInDescription }}</p>

        <div v-if="auth.loginError" class="form-alert" role="alert">
          <span aria-hidden="true"></span>
          <p>{{ auth.loginError }}</p>
        </div>

        <label for="username">{{ zhCN.auth.username }}</label>
        <input
          id="username"
          v-model="username"
          name="username"
          type="text"
          autocomplete="username"
          autocapitalize="none"
          spellcheck="false"
          required
          autofocus
        >

        <label for="password">{{ zhCN.auth.password }}</label>
        <input
          id="password"
          v-model="password"
          name="password"
          type="password"
          autocomplete="current-password"
          required
        >

        <button class="button-primary" type="submit" :disabled="auth.busy">
          {{ auth.busy ? zhCN.auth.signingIn : zhCN.auth.signIn }}
        </button>
        <p class="access-note">{{ zhCN.auth.accessNote }}</p>
      </form>
    </section>
  </main>
</template>

<style scoped>
.login-stage { min-height: 100vh; display: grid; grid-template-columns: minmax(360px, .92fr) minmax(480px, 1.08fr); background: var(--paper); }
.brand-panel { position: relative; display: flex; min-height: 100vh; flex-direction: column; justify-content: space-between; overflow: hidden; padding: clamp(34px, 5vw, 72px); color: #f8fbf9; background: var(--forest-900); }
.brand-panel::before { position: absolute; right: -20%; bottom: 4%; width: 72%; aspect-ratio: 1; border: 1px solid rgba(255,255,255,.1); border-radius: 50%; content: ""; box-shadow: 0 0 0 72px rgba(255,255,255,.025), 0 0 0 144px rgba(255,255,255,.018); }
.brand-panel::after { position: absolute; top: 18%; right: 8%; width: 150px; height: 210px; opacity: .32; background: linear-gradient(135deg, transparent 49%, #caa457 50%, transparent 51%) 0 0/42px 42px; content: ""; }
.brand-lockup, .brand-message, .environment { position: relative; z-index: 1; }
.brand-lockup { display: flex; align-items: center; gap: 14px; }
.brand-mark { display: grid; width: 46px; height: 46px; place-items: center; border: 1px solid rgba(255,255,255,.24); border-radius: 12px; background: rgba(255,255,255,.08); font: 700 .83rem/1 Georgia, serif; letter-spacing: .08em; }
.brand-lockup strong, .brand-lockup span { display: block; }
.brand-lockup strong { font: 600 1.3rem/1.2 Georgia, "Noto Serif SC", serif; letter-spacing: .02em; }
.brand-lockup span { margin-top: 3px; color: #c7d4ce; font-size: .78rem; }
.brand-message { max-width: 600px; margin: 14vh 0 auto; }
.brand-message .eyebrow { color: #d6b66f; }
.brand-message h1 { margin: 0; font: 500 clamp(2.25rem, 4.2vw, 4.5rem)/1.17 Georgia, "Noto Serif SC", serif; letter-spacing: -.025em; }
.brand-message > p:last-child { max-width: 470px; margin: 28px 0 0; color: #bfd0c8; font-size: 1rem; line-height: 1.8; }
.environment { display: flex; align-items: center; gap: 9px; margin: 48px 0 0; color: #b7c8c0; font-size: .76rem; }
.environment span { width: 7px; height: 7px; border-radius: 50%; background: #85c5a1; box-shadow: 0 0 0 4px rgba(133,197,161,.1); }
.form-panel { display: grid; min-height: 100vh; place-items: center; padding: 48px clamp(28px, 8vw, 120px); background: radial-gradient(circle at 100% 0, var(--gold-100), transparent 28%), var(--paper); }
.login-card { width: min(100%, 430px); }
.login-card h2 { margin: 0; color: var(--ink-950); font: 600 clamp(2rem, 4vw, 2.7rem)/1.15 Georgia, "Noto Serif SC", serif; }
.description { margin: 16px 0 34px; color: var(--ink-650); line-height: 1.7; }
label { display: block; margin: 18px 0 8px; color: var(--ink-800); font-size: .83rem; font-weight: 720; }
input { width: 100%; min-height: 48px; padding: 11px 13px; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); color: var(--ink-950); background: #fbfcfb; transition: border-color .15s ease, box-shadow .15s ease; }
input:hover { border-color: #9eaea4; }
input:focus { border-color: var(--forest-750); box-shadow: 0 0 0 4px rgba(29,90,71,.09); outline: 0; }
.button-primary { width: 100%; margin-top: 26px; }
.form-alert { display: flex; align-items: flex-start; gap: 10px; padding: 12px 14px; border: 1px solid #eccaca; border-radius: var(--radius-sm); color: #7f2727; background: var(--danger-soft); font-size: .84rem; }
.form-alert span { display: grid; flex: 0 0 20px; height: 20px; place-items: center; border-radius: 50%; color: white; background: var(--danger); font-size: .72rem; font-weight: 800; }
.form-alert span::before { content: "!"; }
.form-alert p { margin: 0; line-height: 1.5; }
.access-note { margin: 23px 0 0; color: var(--ink-500); font-size: .75rem; line-height: 1.6; text-align: center; }
@media (max-width: 820px) { .login-stage { grid-template-columns: 1fr; } .brand-panel { min-height: auto; padding: 28px; } .brand-message { margin: 72px 0 40px; } .brand-message h1 { font-size: 2.3rem; } .environment { margin-top: 20px; } .form-panel { min-height: auto; padding: 56px 28px 72px; } }
</style>
