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
import PaperDetailPage from "../papers/PaperDetailPage.vue";
import PaperLibraryPage from "../papers/PaperLibraryPage.vue";
import TaskListPage from "../review/tasks/TaskListPage.vue";
import UsersPage from "../admin/UsersPage.vue";
import FilesPage from "../admin/FilesPage.vue";
import AuditPage from "../admin/AuditPage.vue";
import JobsPage from "../admin/JobsPage.vue";
import SystemPage from "../admin/SystemPage.vue";
import PaperCatalogPage from "../admin/PaperCatalogPage.vue";
import PaperCatalogDetailPage from "../admin/PaperCatalogDetailPage.vue";
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
          { path: "", redirect: "/papers" },
          { path: "papers", name: "papers", component: PaperLibraryPage, meta: { roles: publishedRoles } },
          { path: "papers/:paperId", name: "paper-detail", component: PaperDetailPage, meta: { roles: publishedRoles } },
          { path: "review/tasks", name: "review-tasks", component: TaskListPage, meta: { roles: reviewRoles } },
          { path: "review/papers/:paperId", name: "review-paper", component: PlaceholderPage, meta: { roles: reviewRoles } },
          { path: "admin/papers", name: "admin-papers", component: PaperCatalogPage, meta: { roles: adminRoles } },
          { path: "admin/papers/:paperId", name: "admin-paper-detail", component: PaperCatalogDetailPage, meta: { roles: adminRoles } },
          { path: "admin/submissions", name: "admin-submissions", component: PlaceholderPage, meta: { roles: adminRoles } },
          { path: "admin/submissions/:submissionId", name: "admin-submission-detail", component: PlaceholderPage, meta: { roles: adminRoles } },
          { path: "admin/files", component: FilesPage, meta: { roles: adminRoles } },
          { path: "admin/users", component: UsersPage, meta: { roles: adminRoles } },
          { path: "admin/audit", component: AuditPage, meta: { roles: adminRoles } },
          { path: "admin/jobs", name: "admin-jobs", component: JobsPage, meta: { roles: adminRoles } },
          { path: "admin/system", component: SystemPage, meta: { roles: adminRoles } },
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
      return "/";
    }
    if (!auth.user) return { name: "login", query: { redirect: to.fullPath } };
    const roles = to.meta.roles as UserRole[] | undefined;
    if (roles && !roles.includes(auth.user.role)) return "/papers";
    return true;
  });
  return router;
}
