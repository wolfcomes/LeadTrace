<script setup lang="ts">
import { t, locale } from "../i18n";
import { ref } from "vue";
import { useRouter } from "vue-router";

import { zhCN } from "../i18n/zh-CN";
import { useAuthStore } from "./store";

const auth = useAuthStore();
const router = useRouter();
const currentPassword = ref("");
const newPassword = ref("");
const confirmation = ref("");
const busy = ref(false);
const errorMessage = ref<string | null>(null);

async function submit(): Promise<void> {
  errorMessage.value = null;
  if (newPassword.value !== confirmation.value) {
    errorMessage.value = zhCN.auth.passwordMismatch;
    return;
  }
  busy.value = true;
  try {
    await auth.changePassword(currentPassword.value, newPassword.value);
    await router.replace("/");
  } catch {
    errorMessage.value = zhCN.auth.passwordFailure;
  } finally {
    busy.value = false;
    currentPassword.value = "";
    newPassword.value = "";
    confirmation.value = "";
  }
}
</script>

<template>
  <main class="auth-shell auth-shell--centered password-stage">
    <form class="auth-panel password-card" @submit.prevent="submit">
      <div class="security-mark" aria-hidden="true">✓</div>
      <p class="eyebrow">{{ t(zhCN.auth.changeEyebrow) }}</p>
      <h1>{{ t(zhCN.auth.changeTitle) }}</h1>
      <p class="description">{{ t(zhCN.auth.changeDescription) }}</p>
      <p v-if="errorMessage" class="form-alert" role="alert">{{ t(errorMessage) }}</p>
      <div class="form-field">
        <label for="current-password">{{ t(zhCN.auth.currentPassword) }}</label>
        <input id="current-password" v-model="currentPassword" type="password" autocomplete="current-password" required>
      </div>
      <div class="form-field">
        <label for="new-password">{{ t(zhCN.auth.newPassword) }}</label>
        <input id="new-password" v-model="newPassword" type="password" autocomplete="new-password" minlength="6" required>
      </div>
      <div class="form-field">
        <label for="confirm-password">{{ t(zhCN.auth.confirmPassword) }}</label>
        <input id="confirm-password" v-model="confirmation" type="password" autocomplete="new-password" minlength="6" required>
      </div>
      <button class="button-primary" type="submit" :disabled="busy">{{ t(zhCN.auth.changePassword) }}</button>
    </form>
  </main>
</template>
