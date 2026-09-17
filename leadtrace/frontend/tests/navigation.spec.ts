import { mount } from "@vue/test-utils";
import { createPinia, setActivePinia } from "pinia";
import { beforeEach, describe, expect, it } from "vitest";
import { createMemoryHistory } from "vue-router";

import AppShell from "../src/app/AppShell.vue";
import { createAppRouter } from "../src/app/router";
import { useAuthStore, type AuthUser } from "../src/auth/store";


const users: Record<AuthUser["role"], AuthUser> = {
  visitor: {
    username: "visitor.one",
    display_name: "访客一",
    role: "visitor",
    must_change_password: false,
  },
  reviewer: {
    username: "reviewer.one",
    display_name: "核查员一",
    role: "reviewer",
    must_change_password: false,
  },
  admin: {
    username: "admin.one",
    display_name: "管理员一",
    role: "admin",
    must_change_password: false,
  },
};


async function visibleNavigation(role: AuthUser["role"]): Promise<string[]> {
  const router = createAppRouter(createMemoryHistory());
  const auth = useAuthStore();
  auth.acceptSession({ user: users[role], csrf_token: "csrf" });
  await router.push("/");
  await router.isReady();
  const wrapper = mount(AppShell, {
    global: {
      plugins: [router],
      stubs: { RouterView: true },
    },
  });
  return wrapper.findAll("[data-navigation-label]").map((label) => label.text());
}


describe("role-aware application navigation", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows Visitor only published-data navigation", async () => {
    expect(await visibleNavigation("visitor")).toEqual(["已批准文章"]);
  });

  it("shows Reviewer approved Articles and My Tasks without Admin operations", async () => {
    expect(await visibleNavigation("reviewer")).toEqual([
      "已批准文章",
      "我的任务",
    ]);
  });

  it("shows Admin Articles, Submissions, and retained operations", async () => {
    expect(await visibleNavigation("admin")).toEqual([
      "已批准文章",
      "文章目录",
      "提交审批",
      "文件管理",
      "任务队列",
      "用户管理",
      "审计记录",
      "系统状态",
    ]);
  });

  it("renders a named account and a keyboard-visible skip link", async () => {
    const router = createAppRouter(createMemoryHistory());
    useAuthStore().acceptSession({ user: users.admin, csrf_token: "csrf" });
    await router.push("/");
    await router.isReady();
    const wrapper = mount(AppShell, {
      global: { plugins: [router], stubs: { RouterView: true } },
    });

    expect(wrapper.get("[data-account]").text()).toContain("管理员一");
    expect(wrapper.get("[data-account]").text()).toContain("管理员");
    expect(wrapper.get("[data-change-password]").attributes("href")).toBe(
      "/change-password",
    );
    expect(wrapper.get(".skip-link").attributes("href")).toBe("#main-content");
    expect(wrapper.get("main").attributes("id")).toBe("main-content");
  });

  it("exposes application landmarks and labelled navigation icons", async () => {
    const router = createAppRouter(createMemoryHistory());
    useAuthStore().acceptSession({ user: users.admin, csrf_token: "csrf" });
    await router.push("/overview");
    await router.isReady();
    const wrapper = mount(AppShell, {
      global: { plugins: [router], stubs: { RouterView: true } },
    });

    expect(wrapper.get("[data-app-shell]").classes()).toContain("application-shell");
    expect(wrapper.get("[data-app-sidebar]").attributes("aria-label")).toBeTruthy();
    expect(wrapper.find("[data-app-topbar]").exists()).toBe(true);
    expect(wrapper.findAll("[data-navigation-icon]")).toHaveLength(8);
    expect(wrapper.findAll(".nav-link").every((item) => item.attributes("title"))).toBe(true);
  });

  it("lets a signed-in user open the optional password change page", async () => {
    const router = createAppRouter(createMemoryHistory());
    useAuthStore().acceptSession({ user: users.visitor, csrf_token: "csrf" });

    await router.push("/change-password");
    await router.isReady();

    expect(router.currentRoute.value.path).toBe("/change-password");
  });

  it("blocks direct navigation to role-restricted routes", async () => {
    const router = createAppRouter(createMemoryHistory());
    useAuthStore().acceptSession({ user: users.visitor, csrf_token: "csrf" });
    await router.push("/admin/users");
    await router.isReady();
    expect(router.currentRoute.value.path).toBe("/papers");
  });

  it("keeps Visitor sessions out of Reviewer paper routes", async () => {
    const router = createAppRouter(createMemoryHistory());
    useAuthStore().acceptSession({ user: users.visitor, csrf_token: "csrf" });
    await router.push("/review/papers/60000000-0000-4000-8000-000000000001");
    await router.isReady();
    expect(router.currentRoute.value.path).toBe("/papers");
  });

  it("does not register legacy Changeset, Import, or Release product routes", () => {
    const router = createAppRouter(createMemoryHistory());
    const paths = router.getRoutes().map((route) => route.path);

    expect(paths).not.toContain("/review/changesets");
    expect(paths).not.toContain("/admin/imports");
    expect(paths).not.toContain("/admin/releases");
    expect(paths).toContain("/admin/submissions");
    expect(paths).toContain("/review/papers/:paperId");
  });
});
