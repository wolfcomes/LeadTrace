<script setup lang="ts">
import { computed } from "vue";
import { useRouter } from "vue-router";

import type { UserRole } from "../api/schema";
import { useAuthStore } from "../auth/store";
import { zhCN } from "../i18n/zh-CN";

interface NavigationItem {
  label: string;
  to: string;
  section: "published" | "review" | "admin";
  roles: readonly UserRole[];
  symbol: string;
}

const navigation: readonly NavigationItem[] = [
  { label: zhCN.navigation.overview, to: "/overview", section: "published", roles: ["visitor", "reviewer", "admin"], symbol: "OV" },
  { label: zhCN.navigation.papers, to: "/papers", section: "published", roles: ["visitor", "reviewer", "admin"], symbol: "PA" },
  { label: zhCN.navigation.reviewTasks, to: "/review/tasks", section: "review", roles: ["reviewer", "admin"], symbol: "RT" },
  { label: zhCN.navigation.changesets, to: "/review/changesets", section: "review", roles: ["reviewer", "admin"], symbol: "CS" },
  { label: zhCN.navigation.approvals, to: "/admin/approvals", section: "admin", roles: ["admin"], symbol: "AP" },
  { label: zhCN.navigation.files, to: "/admin/files", section: "admin", roles: ["admin"], symbol: "FI" },
  { label: zhCN.navigation.imports, to: "/admin/imports", section: "admin", roles: ["admin"], symbol: "IM" },
  { label: zhCN.navigation.releases, to: "/admin/releases", section: "admin", roles: ["admin"], symbol: "RL" },
  { label: zhCN.navigation.users, to: "/admin/users", section: "admin", roles: ["admin"], symbol: "US" },
  { label: zhCN.navigation.audit, to: "/admin/audit", section: "admin", roles: ["admin"], symbol: "AU" },
  { label: zhCN.navigation.system, to: "/admin/system", section: "admin", roles: ["admin"], symbol: "SY" },
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
  <div class="application-shell">
    <a class="skip-link" href="#main-content">{{ zhCN.navigation.skip }}</a>
    <aside class="sidebar">
      <RouterLink class="brand" to="/overview" aria-label="LeadTrace">
        <span class="brand-mark" aria-hidden="true">LT</span>
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
          >
            <span class="nav-symbol" :data-symbol="item.symbol" aria-hidden="true"></span>
            <span>{{ item.label }}</span>
          </RouterLink>
        </template>
      </nav>

      <div class="sidebar-footer">
        <span class="secure-dot" aria-hidden="true"></span>
        <span>{{ zhCN.shell.protectedWorkspace }}</span>
      </div>
    </aside>

    <div class="workspace">
      <header class="topbar">
        <div class="release-state">
          <span aria-hidden="true"></span>
          {{ zhCN.shell.releasePending }}
        </div>
        <div v-if="auth.user" class="account" data-account>
          <span class="avatar" aria-hidden="true">{{ initials }}</span>
          <span class="account-copy">
            <strong>{{ auth.user.display_name }}</strong>
            <small>{{ zhCN.roles[auth.user.role] }}</small>
          </span>
          <button class="sign-out" type="button" @click="signOut">{{ zhCN.auth.signOut }}</button>
        </div>
      </header>
      <main id="main-content" tabindex="-1">
        <RouterView />
      </main>
    </div>
  </div>
</template>

<style scoped>
.application-shell { min-height: 100vh; background: var(--canvas); }
.skip-link { position: fixed; z-index: 100; top: 10px; left: 10px; padding: 10px 14px; border-radius: 7px; color: white; background: var(--forest-900); transform: translateY(-160%); }
.skip-link:focus { transform: translateY(0); }
.sidebar { position: fixed; z-index: 20; inset: 0 auto 0 0; display: flex; width: 250px; flex-direction: column; padding: 26px 18px 20px; color: #dbe6e0; background: var(--forest-900); }
.brand { display: flex; align-items: center; gap: 12px; padding: 0 7px 24px; color: white; text-decoration: none; }
.brand-mark { display: grid; width: 40px; height: 40px; flex: 0 0 40px; place-items: center; border: 1px solid rgba(255,255,255,.2); border-radius: 11px; background: rgba(255,255,255,.08); font: 700 .75rem/1 Georgia, serif; letter-spacing: .08em; }
.brand-copy strong, .brand-copy small { display: block; }
.brand-copy strong { font: 600 1.12rem/1.2 Georgia, serif; }
.brand-copy small { width: 145px; margin-top: 3px; overflow: hidden; color: #aebfb7; font-size: .65rem; text-overflow: ellipsis; white-space: nowrap; }
nav { flex: 1; overflow-y: auto; padding-right: 2px; }
.nav-section { margin: 24px 10px 7px; color: #779084; font-size: .64rem; font-weight: 750; letter-spacing: .12em; }
.nav-link { display: flex; min-height: 42px; align-items: center; gap: 11px; margin: 3px 0; padding: 8px 10px; border-radius: 8px; color: #c9d6d0; font-size: .84rem; font-weight: 570; text-decoration: none; }
.nav-link:hover { color: white; background: rgba(255,255,255,.07); }
.nav-link.router-link-active { color: white; background: #245c49; box-shadow: inset 3px 0 #d0a652; }
.nav-symbol { display: grid; width: 24px; height: 24px; place-items: center; border: 1px solid rgba(255,255,255,.13); border-radius: 6px; color: #9fb2a9; font-size: .55rem; font-weight: 800; letter-spacing: .04em; }
.nav-symbol::before { content: attr(data-symbol); }
.router-link-active .nav-symbol { color: #f0d28d; border-color: rgba(240,210,141,.35); }
.sidebar-footer { display: flex; align-items: flex-start; gap: 9px; padding: 18px 8px 0; border-top: 1px solid rgba(255,255,255,.1); color: #8da399; font-size: .66rem; line-height: 1.5; }
.secure-dot { width: 7px; height: 7px; flex: 0 0 7px; margin-top: 2px; border-radius: 50%; background: #79bd96; }
.workspace { min-height: 100vh; margin-left: 250px; }
.topbar { position: sticky; z-index: 10; top: 0; display: flex; min-height: 72px; align-items: center; justify-content: space-between; padding: 12px clamp(22px, 4vw, 52px); border-bottom: 1px solid var(--line); background: rgba(255,255,255,.94); backdrop-filter: blur(12px); }
.release-state { display: flex; align-items: center; gap: 8px; color: var(--ink-650); font-size: .74rem; }
.release-state span { width: 7px; height: 7px; border-radius: 50%; background: #b78b38; }
.account { display: flex; align-items: center; gap: 10px; }
.avatar { display: grid; width: 36px; height: 36px; place-items: center; border-radius: 10px; color: var(--forest-900); background: var(--forest-100); font-weight: 760; }
.account-copy strong, .account-copy small { display: block; }
.account-copy strong { color: var(--ink-800); font-size: .78rem; }
.account-copy small { margin-top: 2px; color: var(--ink-500); font-size: .68rem; }
.sign-out { min-height: 34px; margin-left: 10px; padding: 6px 10px; border: 1px solid var(--line); border-radius: 7px; color: var(--ink-650); background: white; font-size: .72rem; cursor: pointer; }
.sign-out:hover { border-color: var(--line-strong); color: var(--ink-950); }
main { min-height: calc(100vh - 72px); }
@media (max-width: 760px) { .sidebar { position: static; width: 100%; min-height: auto; } .application-shell { display: block; } nav { display: flex; flex-wrap: wrap; } .nav-section, .sidebar-footer { display: none; } .nav-link { flex: 1 0 130px; } .workspace { margin-left: 0; } .brand { padding-bottom: 14px; } }
</style>
