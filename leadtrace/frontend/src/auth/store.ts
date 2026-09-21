import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { z } from "zod";

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
const logoutResponseSchema = z.undefined();

interface InFlightRefresh {
  generation: number;
  promise: Promise<void>;
}

interface ActiveCredentialMutation {
  generation: number;
  path: string;
}

export const useAuthStore = defineStore("auth", () => {
  const user = ref<AuthUser | null>(null);
  const csrfToken = ref<string | null>(null);
  const initialized = ref(false);
  const busy = ref(false);
  const loginError = ref<string | null>(null);
  const serviceUnavailable = ref(false);
  const sessionNotice = ref<string | null>(null);
  const credentialMutationInProgress = ref(false);
  const authenticated = computed(() => user.value !== null);
  let sessionSync: SessionSync | undefined;
  let refreshInFlight: InFlightRefresh | undefined;
  let refreshReportsSessionChange = false;
  let sessionGeneration = 0;
  let activeCredentialMutation: ActiveCredentialMutation | undefined;
  let refreshAfterCredentialMutation = false;

  function applySession(session: AuthenticationResponse): void {
    user.value = session.user;
    csrfToken.value = session.csrf_token;
    initialized.value = true;
    loginError.value = null;
    serviceUnavailable.value = false;
  }

  function applySignedOut(): void {
    user.value = null;
    csrfToken.value = null;
    initialized.value = true;
  }

  function acceptSession(session: AuthenticationResponse): void {
    sessionGeneration += 1;
    activeCredentialMutation = undefined;
    credentialMutationInProgress.value = false;
    refreshAfterCredentialMutation = false;
    applySession(session);
    refreshReportsSessionChange = false;
    sessionNotice.value = null;
  }

  function clearSession(): void {
    sessionGeneration += 1;
    activeCredentialMutation = undefined;
    credentialMutationInProgress.value = false;
    refreshAfterCredentialMutation = false;
    applySignedOut();
    refreshReportsSessionChange = false;
    sessionNotice.value = null;
  }

  function beginCredentialMutation(path: string): number {
    if (activeCredentialMutation) {
      throw new Error("Another credential mutation is already in progress.");
    }
    sessionGeneration += 1;
    activeCredentialMutation = { generation: sessionGeneration, path };
    credentialMutationInProgress.value = true;
    return sessionGeneration;
  }

  function finishCredentialMutation(generation: number): void {
    if (activeCredentialMutation?.generation !== generation) return;
    activeCredentialMutation = undefined;
    credentialMutationInProgress.value = false;
    if (refreshAfterCredentialMutation) {
      refreshAfterCredentialMutation = false;
      void refreshSession({
        sessionChanged: refreshReportsSessionChange,
      }).catch(() => undefined);
    }
  }

  function completeSessionMutation(
    generation: number,
    session: AuthenticationResponse,
  ): boolean {
    if (
      generation !== sessionGeneration
      || activeCredentialMutation?.generation !== generation
    ) return false;
    sessionGeneration += 1;
    applySession(session);
    if (!refreshAfterCredentialMutation) refreshReportsSessionChange = false;
    sessionNotice.value = null;
    return true;
  }

  function completeLogout(generation: number): boolean {
    if (
      generation !== sessionGeneration
      || activeCredentialMutation?.generation !== generation
    ) return false;
    sessionGeneration += 1;
    applySignedOut();
    sessionNotice.value = null;
    return true;
  }

  function refreshSession(options: SessionRefreshOptions = {}): Promise<void> {
    refreshReportsSessionChange ||= options.sessionChanged === true;
    if (activeCredentialMutation) {
      refreshAfterCredentialMutation = true;
      return Promise.resolve();
    }
    const generation = sessionGeneration;
    if (refreshInFlight?.generation === generation) return refreshInFlight.promise;

    const promise = (async () => {
      try {
        const session = await apiRequest(
          "/api/v1/auth/session",
          authenticationResponseSchema,
          { suppressUnauthorizedHandler: true },
        );
        if (generation !== sessionGeneration || activeCredentialMutation) return;
        sessionGeneration += 1;
        applySession(session);
        if (refreshReportsSessionChange) {
          sessionNotice.value = zhCN.auth.sessionChanged;
        }
        refreshReportsSessionChange = false;
      } catch (error) {
        if (generation !== sessionGeneration || activeCredentialMutation) return;
        if (
          error instanceof ApiError
          && error.status === 401
        ) {
          sessionGeneration += 1;
          applySignedOut();
          refreshReportsSessionChange = false;
          sessionNotice.value = null;
          return;
        }
        throw error;
      }
    })().finally(() => {
      if (refreshInFlight?.promise === promise) refreshInFlight = undefined;
    });
    refreshInFlight = { generation, promise };
    return promise;
  }

  function recoverFromUnauthorized(
    _path: string,
    requestGeneration?: number,
  ): boolean {
    if (
      requestGeneration !== undefined
      && requestGeneration !== sessionGeneration
    ) return false;
    if (activeCredentialMutation) {
      refreshAfterCredentialMutation = true;
      return false;
    }
    clearSession();
    return true;
  }

  async function recoverFromCsrfFailure(path: string): Promise<void> {
    if (activeCredentialMutation && activeCredentialMutation.path !== path) {
      refreshReportsSessionChange = true;
      refreshAfterCredentialMutation = true;
      return;
    }
    if (activeCredentialMutation?.path === path) {
      sessionGeneration += 1;
      activeCredentialMutation = undefined;
      credentialMutationInProgress.value = false;
    }
    sessionNotice.value = null;
    await refreshSession({ sessionChanged: true });
  }

  function startSessionSync(): void {
    if (sessionSync || typeof window === "undefined" || typeof document === "undefined") return;
    activeSessionSync?.stop();
    let storage: Storage | undefined;
    try {
      storage = window.localStorage;
    } catch {
      storage = undefined;
    }
    sessionSync = createSessionSync({
      window,
      document,
      storage,
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
    refreshReportsSessionChange = false;
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
    const generation = beginCredentialMutation("/api/v1/auth/login");
    busy.value = true;
    loginError.value = null;
    serviceUnavailable.value = false;
    try {
      const session = await apiRequest(
        "/api/v1/auth/login",
        authenticationResponseSchema,
        {
          method: "POST",
          body: { username, password },
          suppressUnauthorizedHandler: true,
        },
      );
      if (!completeSessionMutation(generation, session)) return false;
      publishCredentialsChanged();
      return true;
    } catch (error) {
      loginError.value = error instanceof ApiError && error.kind === "unavailable"
        ? zhCN.auth.unavailableError
        : zhCN.auth.genericError;
      return false;
    } finally {
      finishCredentialMutation(generation);
      busy.value = false;
    }
  }

  async function changePassword(
    currentPassword: string,
    newPassword: string,
  ): Promise<void> {
    const generation = beginCredentialMutation("/api/v1/auth/password");
    try {
      const session = await apiRequest(
        "/api/v1/auth/password",
        authenticationResponseSchema,
        {
          method: "POST",
          csrfToken: csrfToken.value,
          body: { current_password: currentPassword, new_password: newPassword },
        },
      );
      if (completeSessionMutation(generation, session)) {
        publishCredentialsChanged();
      }
    } finally {
      finishCredentialMutation(generation);
    }
  }

  async function logout(): Promise<void> {
    const generation = beginCredentialMutation("/api/v1/auth/logout");
    sessionNotice.value = null;
    try {
      await apiRequest(
        "/api/v1/auth/logout",
        logoutResponseSchema,
        {
          method: "POST",
          csrfToken: csrfToken.value,
          suppressUnauthorizedHandler: true,
        },
      );
      if (completeLogout(generation)) publishCredentialsChanged();
    } catch (error) {
      if (error instanceof ApiError && error.status === 401) {
        if (completeLogout(generation)) publishCredentialsChanged();
        return;
      }
      if (!(error instanceof ApiError
        && error.code === "CSRF_VALIDATION_FAILED"
        && sessionNotice.value === zhCN.auth.sessionChanged)) {
        sessionNotice.value = zhCN.auth.logoutFailed;
      }
      throw error;
    } finally {
      finishCredentialMutation(generation);
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
    credentialMutationInProgress,
    authenticated,
    acceptSession,
    clearSession,
    restore,
    refreshSession,
    recoverFromUnauthorized,
    recoverFromCsrfFailure,
    startSessionSync,
    stopSessionSync,
    dismissSessionNotice,
    currentSessionGeneration: () => sessionGeneration,
    login,
    changePassword,
    logout,
  };
});
