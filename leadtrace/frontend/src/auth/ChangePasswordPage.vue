<script setup lang="ts">
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
  <main class="password-stage">
    <form class="password-card" @submit.prevent="submit">
      <div class="security-mark" aria-hidden="true">✓</div>
      <p class="eyebrow">{{ zhCN.auth.changeEyebrow }}</p>
      <h1>{{ zhCN.auth.changeTitle }}</h1>
      <p class="description">{{ zhCN.auth.changeDescription }}</p>
      <p v-if="errorMessage" class="form-alert" role="alert">{{ errorMessage }}</p>
      <label for="current-password">{{ zhCN.auth.currentPassword }}</label>
      <input id="current-password" v-model="currentPassword" type="password" autocomplete="current-password" required>
      <label for="new-password">{{ zhCN.auth.newPassword }}</label>
      <input id="new-password" v-model="newPassword" type="password" autocomplete="new-password" required>
      <label for="confirm-password">{{ zhCN.auth.confirmPassword }}</label>
      <input id="confirm-password" v-model="confirmation" type="password" autocomplete="new-password" required>
      <button class="button-primary" type="submit" :disabled="busy">{{ zhCN.auth.changePassword }}</button>
    </form>
  </main>
</template>

<style scoped>
.password-stage { display: grid; min-height: 100vh; place-items: center; padding: 36px 20px; background: radial-gradient(circle at 12% 15%, var(--forest-100), transparent 30%), radial-gradient(circle at 88% 82%, var(--gold-100), transparent 25%), var(--canvas); }
.password-card { width: min(100%, 510px); padding: clamp(30px, 5vw, 52px); border: 1px solid var(--line); border-radius: var(--radius-lg); background: var(--paper); box-shadow: var(--shadow-md); }
.security-mark { display: grid; width: 48px; height: 48px; margin-bottom: 28px; place-items: center; border-radius: 14px; color: var(--paper); background: var(--forest-900); font-weight: 800; }
h1 { margin: 0; color: var(--ink-950); font: 600 2.25rem/1.2 Georgia, "Noto Serif SC", serif; }
.description { margin: 14px 0 28px; color: var(--ink-650); line-height: 1.7; }
label { display: block; margin: 16px 0 7px; color: var(--ink-800); font-size: .83rem; font-weight: 720; }
input { width: 100%; min-height: 46px; padding: 10px 12px; border: 1px solid var(--line-strong); border-radius: var(--radius-sm); background: #fbfcfb; }
input:focus { border-color: var(--forest-750); box-shadow: 0 0 0 4px rgba(29,90,71,.09); outline: 0; }
.button-primary { width: 100%; margin-top: 26px; }
.form-alert { padding: 11px 13px; border: 1px solid #eccaca; border-radius: var(--radius-sm); color: #7f2727; background: var(--danger-soft); font-size: .84rem; }
</style>
