<script setup lang="ts">
import { t, locale } from "../i18n";
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
  const destination = typeof route.query.redirect === "string"
    ? route.query.redirect
    : "/";
  await router.replace(destination.startsWith("/") ? destination : "/");
}
</script>

<template>
  <main class="auth-shell login-stage">
    <section class="brand-panel" aria-labelledby="platform-name">
      <div class="brand-lockup">
        <span class="brand-mark" aria-hidden="true">LT</span>
        <div>
          <strong id="platform-name">{{ t(zhCN.brand.name) }}</strong>
          <span>{{ t(zhCN.brand.descriptor) }}</span>
        </div>
      </div>
      <div class="brand-message">
        <p class="eyebrow">{{ t(zhCN.brand.eyebrow) }}</p>
        <h1>{{ t(zhCN.brand.headline) }}</h1>
        <p>{{ t(zhCN.brand.introduction) }}</p>
      </div>
      <p class="environment"><span aria-hidden="true"></span>{{ t(zhCN.brand.environment) }}</p>
    </section>

    <section class="form-panel">
      <form class="auth-panel login-card" novalidate @submit.prevent="submit">
        <p class="eyebrow">{{ t(zhCN.auth.signInEyebrow) }}</p>
        <h2>{{ t(zhCN.auth.signInTitle) }}</h2>
        <p class="description">{{ t(zhCN.auth.signInDescription) }}</p>

        <div v-if="auth.loginError" id="login-error" class="form-alert" role="alert">
          <span aria-hidden="true"></span>
          <p>{{ t(auth.loginError) }}</p>
        </div>

        <div class="form-field">
          <label for="username">{{ t(zhCN.auth.username) }}</label>
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
            :aria-describedby="auth.loginError ? 'login-error' : undefined"
          >
        </div>

        <div class="form-field">
          <label for="password">{{ t(zhCN.auth.password) }}</label>
          <input
            id="password"
            v-model="password"
            name="password"
            type="password"
            autocomplete="current-password"
            required
            :aria-describedby="auth.loginError ? 'login-error' : undefined"
          >
        </div>

        <button class="button-primary" type="submit" :disabled="auth.busy">
          {{ t(auth.busy ? zhCN.auth.signingIn : zhCN.auth.signIn) }}
        </button>
        <p class="access-note">{{ t(zhCN.auth.accessNote) }}</p>
      </form>
    </section>
  </main>
</template>
