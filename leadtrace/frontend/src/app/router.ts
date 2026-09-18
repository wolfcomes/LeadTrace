import {
  createRouter,
  createWebHistory,
  type Router,
  type RouterHistory,
} from "vue-router";
import { watch, type App, type WatchStopHandle } from "vue";
import { getActivePinia, setActivePinia } from "pinia";

import {
  setCsrfValidationFailedHandler,
  setUnauthorizedHandler,
} from "../api/client";
import type { UserRole } from "../api/schema";
import ChangePasswordPage from "../auth/ChangePasswordPage.vue";
import LoginPage from "../auth/LoginPage.vue";
import { useAuthStore } from "../auth/store";
import PaperDetailPage from "../papers/PaperDetailPage.vue";
import PaperLibraryPage from "../papers/PaperLibraryPage.vue";
import TaskListPage from "../review/tasks/TaskListPage.vue";
import PaperWorkspacePage from "../review/paper/PaperWorkspacePage.vue";
import UsersPage from "../admin/UsersPage.vue";
import FilesPage from "../admin/FilesPage.vue";
import AuditPage from "../admin/AuditPage.vue";
import JobsPage from "../admin/JobsPage.vue";
import SystemPage from "../admin/SystemPage.vue";
import PaperCatalogPage from "../admin/PaperCatalogPage.vue";
import PaperCatalogDetailPage from "../admin/PaperCatalogDetailPage.vue";
import ApprovalCenterPage from "../approvals/ApprovalCenterPage.vue";
import PaperSubmissionReviewPage from "../approvals/PaperSubmissionReviewPage.vue";
import AppShell from "./AppShell.vue";

const publishedRoles: UserRole[] = ["visitor", "reviewer", "admin"];
const reviewRoles: UserRole[] = ["reviewer", "admin"];
const adminRoles: UserRole[] = ["admin"];
let disposeActiveRouter: (() => void) | undefined;

function safeRedirect(value: unknown): string {
  return typeof value === "string"
    && value.startsWith("/")
    && !value.startsWith("//")
    ? value
    : "/papers";
}

export function createAppRouter(
  history: RouterHistory = createWebHistory(),
): Router {
  const pinia = getActivePinia();
  if (!pinia) throw new Error("Pinia must be active before creating the router");
  const auth = useAuthStore(pinia);
  disposeActiveRouter?.();
  setActivePinia(pinia);
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
          { path: "review/papers/:paperId", name: "review-paper", component: PaperWorkspacePage, meta: { roles: reviewRoles } },
          { path: "admin/papers", name: "admin-papers", component: PaperCatalogPage, meta: { roles: adminRoles } },
          { path: "admin/papers/:paperId", name: "admin-paper-detail", component: PaperCatalogDetailPage, meta: { roles: adminRoles } },
          { path: "admin/submissions", name: "admin-submissions", component: ApprovalCenterPage, meta: { roles: adminRoles } },
          { path: "admin/submissions/:submissionId", name: "admin-submission-detail", component: PaperSubmissionReviewPage, meta: { roles: adminRoles } },
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
  let stopAuthorizationWatch: WatchStopHandle | undefined;
  let disposed = false;

  function reconcileCurrentRoute(
    username: string | undefined,
    previousUsername: string | undefined,
  ): void {
    const route = router.currentRoute.value;
    if (route.matched.length === 0) return;
    if (!username || !auth.user) {
      if (route.name !== "login") {
        void router.replace({
          name: "login",
          query: { redirect: route.fullPath },
        });
      }
      return;
    }
    if (route.name === "login") {
      void router.replace(safeRedirect(route.query.redirect));
      return;
    }
    if (previousUsername && previousUsername !== username) {
      void router.replace("/papers");
      return;
    }
    if (route.meta.public) return;
    const roles = route.meta.roles as UserRole[] | undefined;
    if (roles && !roles.includes(auth.user.role)) {
      void router.replace("/papers");
    }
  }

  setUnauthorizedHandler(() => {
    auth.clearSession();
    const redirect = router.currentRoute.value.fullPath;
    if (router.currentRoute.value.name !== "login") {
      void router.replace({ name: "login", query: { redirect } });
    }
  });
  setCsrfValidationFailedHandler(async () => {
    await auth.recoverFromCsrfFailure();
  });
  stopAuthorizationWatch = watch(
    [() => auth.user?.username, () => auth.user?.role],
    ([username], [previousUsername]) => {
      reconcileCurrentRoute(username, previousUsername);
    },
    { flush: "sync" },
  );
  auth.startSessionSync();

  function dispose(): void {
    if (disposed) return;
    disposed = true;
    stopAuthorizationWatch?.();
    auth.stopSessionSync();
    if (disposeActiveRouter === dispose) {
      setUnauthorizedHandler(undefined);
      setCsrfValidationFailedHandler(undefined);
      disposeActiveRouter = undefined;
    }
  }

  disposeActiveRouter = dispose;
  const installRouter = router.install;
  router.install = (app: App): void => {
    installRouter.call(router, app);
    app.onUnmount(dispose);
  };

  router.beforeEach(async (to) => {
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
