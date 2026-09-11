import { defineComponent, h } from "vue";
import {
  createRouter,
  createWebHistory,
  type Router,
  type RouterHistory,
} from "vue-router";

import { setUnauthorizedHandler } from "../api/client";
import type { UserRole } from "../api/schema";
import ChangePasswordPage from "../auth/ChangePasswordPage.vue";
import LoginPage from "../auth/LoginPage.vue";
import { useAuthStore } from "../auth/store";
import { zhCN } from "../i18n/zh-CN";
import OverviewPage from "../papers/OverviewPage.vue";
import PaperDetailPage from "../papers/PaperDetailPage.vue";
import PaperLibraryPage from "../papers/PaperLibraryPage.vue";
import AppShell from "./AppShell.vue";

const PlaceholderPage = defineComponent({
  setup() {
    return () => h("section", { class: "placeholder-page" }, [
      h("p", { class: "eyebrow" }, zhCN.shell.placeholderEyebrow),
      h("h1", zhCN.shell.placeholderTitle),
      h("p", zhCN.shell.placeholderBody),
    ]);
  },
});

const publishedRoles: UserRole[] = ["visitor", "reviewer", "admin"];
const reviewRoles: UserRole[] = ["reviewer", "admin"];
const adminRoles: UserRole[] = ["admin"];

export function createAppRouter(
  history: RouterHistory = createWebHistory(),
): Router {
  const router = createRouter({
    history,
    routes: [
      { path: "/login", name: "login", component: LoginPage, meta: { public: true } },
      {
        path: "/change-password",
        name: "change-password",
        component: ChangePasswordPage,
      },
      {
        path: "/",
        component: AppShell,
        children: [
          { path: "", redirect: "/overview" },
          { path: "overview", name: "overview", component: OverviewPage, meta: { roles: publishedRoles } },
          { path: "papers", name: "papers", component: PaperLibraryPage, meta: { roles: publishedRoles } },
          { path: "papers/:paperId", name: "paper-detail", component: PaperDetailPage, meta: { roles: publishedRoles } },
          { path: "review/tasks", component: PlaceholderPage, meta: { roles: reviewRoles } },
          { path: "review/changesets", component: PlaceholderPage, meta: { roles: reviewRoles } },
          { path: "review/changesets/:changesetId", component: PlaceholderPage, meta: { roles: reviewRoles } },
          { path: "admin/approvals", component: PlaceholderPage, meta: { roles: adminRoles } },
          { path: "admin/files", component: PlaceholderPage, meta: { roles: adminRoles } },
          { path: "admin/imports", component: PlaceholderPage, meta: { roles: adminRoles } },
          { path: "admin/releases", component: PlaceholderPage, meta: { roles: adminRoles } },
          { path: "admin/users", component: PlaceholderPage, meta: { roles: adminRoles } },
          { path: "admin/audit", component: PlaceholderPage, meta: { roles: adminRoles } },
          { path: "admin/system", component: PlaceholderPage, meta: { roles: adminRoles } },
        ],
      },
      { path: "/:pathMatch(.*)*", redirect: "/" },
    ],
  });

  setUnauthorizedHandler(() => {
    const auth = useAuthStore();
    auth.clearSession();
    const redirect = router.currentRoute.value.fullPath;
    if (router.currentRoute.value.name !== "login") {
      void router.replace({ name: "login", query: { redirect } });
    }
  });

  router.beforeEach(async (to) => {
    const auth = useAuthStore();
    if (!auth.initialized) {
      try {
        await auth.restore();
      } catch {
        return { name: "login", query: { redirect: to.fullPath } };
      }
    }
    if (to.meta.public) {
      if (!auth.user) return true;
      return auth.user.must_change_password ? { name: "change-password" } : "/";
    }
    if (!auth.user) return { name: "login", query: { redirect: to.fullPath } };
    if (auth.user.must_change_password && to.name !== "change-password") {
      return { name: "change-password" };
    }
    if (!auth.user.must_change_password && to.name === "change-password") return "/";
    const roles = to.meta.roles as UserRole[] | undefined;
    if (roles && !roles.includes(auth.user.role)) return "/";
    return true;
  });
  return router;
}
