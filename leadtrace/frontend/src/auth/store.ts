import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { ApiError, apiRequest } from "../api/client";
import {
  authenticationResponseSchema,
  type AuthenticationResponse,
  type AuthUser,
} from "../api/schema";
import { zhCN } from "../i18n/zh-CN";

export type { AuthUser } from "../api/schema";

export const useAuthStore = defineStore("auth", () => {
  const user = ref<AuthUser | null>(null);
  const csrfToken = ref<string | null>(null);
  const initialized = ref(false);
  const busy = ref(false);
  const loginError = ref<string | null>(null);
  const authenticated = computed(() => user.value !== null);

  function acceptSession(session: AuthenticationResponse): void {
    user.value = session.user;
    csrfToken.value = session.csrf_token;
    initialized.value = true;
    loginError.value = null;
  }

  function clearSession(): void {
    user.value = null;
    csrfToken.value = null;
    initialized.value = true;
  }

  async function restore(): Promise<void> {
    if (initialized.value) return;
    try {
      acceptSession(await apiRequest(
        "/api/v1/auth/session",
        authenticationResponseSchema,
        { suppressUnauthorizedHandler: true },
      ));
    } catch (error) {
      clearSession();
      if (!(error instanceof ApiError && error.status === 401)) throw error;
    }
  }

  async function login(username: string, password: string): Promise<boolean> {
    busy.value = true;
    loginError.value = null;
    try {
      acceptSession(await apiRequest(
        "/api/v1/auth/login",
        authenticationResponseSchema,
        {
          method: "POST",
          body: { username, password },
          suppressUnauthorizedHandler: true,
        },
      ));
      return true;
    } catch {
      loginError.value = zhCN.auth.genericError;
      return false;
    } finally {
      busy.value = false;
    }
  }

  async function changePassword(
    currentPassword: string,
    newPassword: string,
  ): Promise<void> {
    acceptSession(await apiRequest(
      "/api/v1/auth/password",
      authenticationResponseSchema,
      {
        method: "POST",
        csrfToken: csrfToken.value,
        body: { current_password: currentPassword, new_password: newPassword },
      },
    ));
  }

  async function logout(): Promise<void> {
    try {
      await apiRequest(
        "/api/v1/auth/logout",
        authenticationResponseSchema.optional(),
        { method: "POST", csrfToken: csrfToken.value },
      );
    } finally {
      clearSession();
    }
  }

  return {
    user,
    csrfToken,
    initialized,
    busy,
    loginError,
    authenticated,
    acceptSession,
    clearSession,
    restore,
    login,
    changePassword,
    logout,
  };
});
