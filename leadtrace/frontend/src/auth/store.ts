import { defineStore } from "pinia";
import { computed, ref } from "vue";

import { ApiError, apiRequest } from "../api/client";
import {
  authenticationResponseSchema,
  type AuthenticationResponse,
  type AuthUser,
} from "../api/schema";
import { zhCN } from "../i18n/zh-CN";
import {
  createSessionSync,
  type SessionRefreshOptions,
  type SessionSync,
} from "./sessionSync";

export type { AuthUser } from "../api/schema";

let activeSessionSync: SessionSync | undefined;

export const useAuthStore = defineStore("auth", () => {
  const user = ref<AuthUser | null>(null);
  const csrfToken = ref<string | null>(null);
  const initialized = ref(false);
  const busy = ref(false);
  const loginError = ref<string | null>(null);
  const serviceUnavailable = ref(false);
  const sessionNotice = ref<string | null>(null);
  const authenticated = computed(() => user.value !== null);
  let sessionSync: SessionSync | undefined;
  let refreshInFlight: Promise<void> | undefined;
  let refreshReportsSessionChange = false;

  function acceptSession(session: AuthenticationResponse): void {
    user.value = session.user;
    csrfToken.value = session.csrf_token;
    initialized.value = true;
    loginError.value = null;
    serviceUnavailable.value = false;
  }

  function clearSession(): void {
    user.value = null;
    csrfToken.value = null;
    initialized.value = true;
  }

  function refreshSession(options: SessionRefreshOptions = {}): Promise<void> {
    refreshReportsSessionChange ||= options.sessionChanged === true;
    if (refreshInFlight) return refreshInFlight;

    refreshInFlight = (async () => {
      try {
        acceptSession(await apiRequest(
          "/api/v1/auth/session",
          authenticationResponseSchema,
          { suppressUnauthorizedHandler: true },
        ));
        if (refreshReportsSessionChange) {
          sessionNotice.value = zhCN.auth.sessionChanged;
        }
      } catch (error) {
        if (error instanceof ApiError && error.status === 401) {
          clearSession();
          return;
        }
        throw error;
      }
    })().finally(() => {
      refreshInFlight = undefined;
      refreshReportsSessionChange = false;
    });
    return refreshInFlight;
  }

  function startSessionSync(): void {
    if (sessionSync || typeof window === "undefined" || typeof document === "undefined") return;
    activeSessionSync?.stop();
    sessionSync = createSessionSync({
      window,
      document,
      storage: window.localStorage,
      BroadcastChannel: typeof globalThis.BroadcastChannel === "function"
        ? globalThis.BroadcastChannel
        : undefined,
      refreshSession,
    });
    activeSessionSync = sessionSync;
  }

  function stopSessionSync(): void {
    if (!sessionSync) return;
    sessionSync.stop();
    if (activeSessionSync === sessionSync) activeSessionSync = undefined;
    sessionSync = undefined;
  }

  function publishCredentialsChanged(): void {
    sessionSync?.publishCredentialsChanged();
  }

  function dismissSessionNotice(): void {
    sessionNotice.value = null;
  }

  async function restore(): Promise<void> {
    if (initialized.value) return;
    try {
      await refreshSession();
    } catch (error) {
      initialized.value = true;
      if (error instanceof ApiError && error.kind === "unavailable") {
        serviceUnavailable.value = true;
        loginError.value = zhCN.auth.unavailableError;
        return;
      }
      if (!(error instanceof ApiError && error.status === 401)) throw error;
    }
  }

  async function login(username: string, password: string): Promise<boolean> {
    busy.value = true;
    loginError.value = null;
    serviceUnavailable.value = false;
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
      publishCredentialsChanged();
      return true;
    } catch (error) {
      loginError.value = error instanceof ApiError && error.kind === "unavailable"
        ? zhCN.auth.unavailableError
        : zhCN.auth.genericError;
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
    publishCredentialsChanged();
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
      sessionNotice.value = null;
      publishCredentialsChanged();
    }
  }

  return {
    user,
    csrfToken,
    initialized,
    busy,
    loginError,
    serviceUnavailable,
    sessionNotice,
    authenticated,
    acceptSession,
    clearSession,
    restore,
    refreshSession,
    startSessionSync,
    stopSessionSync,
    dismissSessionNotice,
    login,
    changePassword,
    logout,
  };
});
