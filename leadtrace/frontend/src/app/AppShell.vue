<script setup lang="ts">
import {
  Activity,
  BookOpenText,
  ClipboardCheck,
  FileSearch,
  Files,
  ScrollText,
  Users,
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
  await auth.logout();
  await router.replace("/login");
}
</script>

<template>
  <div class="application-shell" data-app-shell>
    <a class="skip-link" href="#main-content">{{ zhCN.navigation.skip }}</a>
    <aside class="sidebar" data-app-sidebar :aria-label="zhCN.brand.name">
      <RouterLink class="brand" to="/papers" aria-label="LeadTrace">
        <span class="brand-mark" aria-hidden="true">LT<i></i></span>
        <span class="brand-copy">
          <strong>{{ zhCN.brand.name }}</strong>
          <small>{{ zhCN.brand.descriptor }}</small>
        </span>
      </RouterLink>

      <nav data-navigation :aria-label="zhCN.navigation.primary">
        <template v-for="section in ['published', 'review', 'admin'] as const" :key="section">
          <p v-if="visibleNavigation.some((item) => item.section === section)" class="nav-section">
            {{ zhCN.shell.sections[section] }}
          </p>
          <RouterLink
            v-for="item in visibleNavigation.filter((entry) => entry.section === section)"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            :title="item.label"
          >
            <component :is="item.icon" class="nav-icon" data-navigation-icon :size="16" aria-hidden="true" />
            <span data-navigation-label>{{ item.label }}</span>
          </RouterLink>
        </template>
      </nav>

      <div class="sidebar-footer">
        <span class="secure-dot" aria-hidden="true"></span>
        <span>{{ zhCN.shell.protectedWorkspace }}</span>
      </div>
    </aside>

    <div class="workspace">
      <header class="topbar" data-app-topbar>
        <div class="release-state">
          <span aria-hidden="true"></span>
          {{ zhCN.shell.publicationState }}
        </div>
        <div v-if="auth.user" class="account" data-account>
          <span class="avatar" aria-hidden="true">{{ initials }}</span>
          <span class="account-copy">
            <strong>{{ auth.user.display_name }}</strong>
            <small>{{ zhCN.roles[auth.user.role] }}</small>
          </span>
          <RouterLink class="account-action" data-change-password to="/change-password">
            {{ zhCN.auth.changePassword }}
          </RouterLink>
          <button class="sign-out" type="button" @click="signOut">{{ zhCN.auth.signOut }}</button>
        </div>
      </header>
      <main id="main-content" tabindex="-1">
        <RouterView />
      </main>
    </div>
  </div>
</template>
