<script setup lang="ts">
import { t, locale } from "../i18n";
import {
  Activity,
  BookOpenText,
  ClipboardCheck,
  FileSearch,
  Files,
  ListTodo,
  ScrollText,
  Users,
  X,
} from "lucide-vue-next";
import { computed, type Component } from "vue";
import { useRouter } from "vue-router";

import type { UserRole } from "../api/schema";
import { useAuthStore } from "../auth/store";
import { zhCN } from "../i18n/zh-CN";

interface NavigationItem {
  label: string;
  to: string;
  section: "published" | "review" | "admin";
  roles: readonly UserRole[];
  icon: Component;
}

const navigation: readonly NavigationItem[] = [
  { label: zhCN.navigation.approvedArticles, to: "/papers", section: "published", roles: ["visitor", "reviewer", "admin"], icon: BookOpenText },
  { label: zhCN.navigation.myTasks, to: "/review/tasks", section: "review", roles: ["reviewer"], icon: ClipboardCheck },
  { label: zhCN.navigation.articleCatalog, to: "/admin/papers", section: "admin", roles: ["admin"], icon: FileSearch },
  { label: zhCN.navigation.submissions, to: "/admin/submissions", section: "admin", roles: ["admin"], icon: ClipboardCheck },
  { label: zhCN.navigation.files, to: "/admin/files", section: "admin", roles: ["admin"], icon: Files },
  { label: "AI 任务中心", to: "/admin/ai-tasks", section: "admin", roles: ["admin"], icon: ListTodo },
  { label: zhCN.navigation.jobs, to: "/admin/jobs", section: "admin", roles: ["admin"], icon: ListTodo },
  { label: zhCN.navigation.users, to: "/admin/users", section: "admin", roles: ["admin"], icon: Users },
  { label: zhCN.navigation.audit, to: "/admin/audit", section: "admin", roles: ["admin"], icon: ScrollText },
  { label: zhCN.navigation.system, to: "/admin/system", section: "admin", roles: ["admin"], icon: Activity },
];

const auth = useAuthStore();
const router = useRouter();
const visibleNavigation = computed(() => navigation.filter(
  (item) => auth.user && item.roles.includes(auth.user.role),
));
const initials = computed(() => auth.user?.display_name.trim().slice(0, 1) || "L");

async function signOut(): Promise<void> {
  try {
    await auth.logout();
    await router.replace("/login");
  } catch {
    // The store preserves the active session and exposes the relevant notice.
  }
}
</script>

<template>
  <div class="application-shell" data-app-shell>
    <a class="skip-link" href="#main-content">{{ t(zhCN.navigation.skip) }}</a>
    <aside class="sidebar" data-app-sidebar :aria-label="t(zhCN.brand.name)">
      <RouterLink class="brand" to="/papers" aria-label="LeadTrace">
        <span class="brand-mark" aria-hidden="true">LT<i></i></span>
        <span class="brand-copy">
          <strong>{{ t(zhCN.brand.name) }}</strong>
          <small>{{ t(zhCN.brand.descriptor) }}</small>
        </span>
      </RouterLink>

      <nav data-navigation :aria-label="t(zhCN.navigation.primary)">
        <template v-for="section in ['published', 'review', 'admin'] as const" :key="section">
          <p v-if="visibleNavigation.some((item) => item.section === section)" class="nav-section">
            {{ t(zhCN.shell.sections[section]) }}
          </p>
          <RouterLink
            v-for="item in visibleNavigation.filter((entry) => entry.section === section)"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            :title="t(item.label)"
          >
            <component :is="item.icon" class="nav-icon" data-navigation-icon :size="16" aria-hidden="true" />
            <span data-navigation-label>{{ t(item.label) }}</span>
          </RouterLink>
        </template>
      </nav>

      <div class="sidebar-footer">
        <span class="secure-dot" aria-hidden="true"></span>
        <span>{{ t(zhCN.shell.protectedWorkspace) }}</span>
      </div>
    </aside>

    <div class="workspace">
      <header class="topbar" data-app-topbar>
        <div class="release-state">
          <span aria-hidden="true"></span>
          {{ t(zhCN.shell.publicationState) }}
        </div>
        <div v-if="auth.user" class="account" data-account>
          <span class="avatar" aria-hidden="true">{{ initials }}</span>
          <span class="account-copy">
            <strong>{{ auth.user.display_name }}</strong>
            <small>{{ t(zhCN.roles[auth.user.role]) }}</small>
          </span>
          <RouterLink class="account-action" data-change-password to="/change-password">
            {{ t(zhCN.auth.changePassword) }}
          </RouterLink>
          <button class="sign-out" type="button" :disabled="auth.credentialMutationInProgress" @click="signOut">{{ t(zhCN.auth.signOut) }}</button>
        </div>
      </header>
      <div
        v-if="auth.sessionNotice"
        class="inline-feedback is-warning"
        data-session-notice
        role="alert"
      >
        <span>{{ t(auth.sessionNotice) }}</span>
        <button
          class="icon-button"
          data-dismiss-session-notice
          type="button"
          :aria-label="t(zhCN.auth.dismissSessionNotice)"
          :title="t(zhCN.auth.dismissSessionNotice)"
          @click="auth.dismissSessionNotice"
        >
          <X :size="16" aria-hidden="true" />
        </button>
      </div>
      <main id="main-content" tabindex="-1">
        <RouterView />
      </main>
    </div>
  </div>
</template>
