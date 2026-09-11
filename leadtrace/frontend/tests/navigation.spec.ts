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
  return wrapper.findAll("[data-navigation] a").map((link) => link.text());
}


describe("role-aware application navigation", () => {
  beforeEach(() => {
    setActivePinia(createPinia());
  });

  it("shows Visitor only published-data navigation", async () => {
    expect(await visibleNavigation("visitor")).toEqual(["数据概览", "文献库"]);
  });

  it("adds review workspaces for Reviewer without Admin operations", async () => {
    expect(await visibleNavigation("reviewer")).toEqual([
      "数据概览",
      "文献库",
      "审核任务",
      "修改集",
    ]);
  });

  it("shows Admin publication and operations navigation", async () => {
    expect(await visibleNavigation("admin")).toEqual([
      "数据概览",
      "文献库",
      "审核任务",
      "修改集",
      "审批中心",
      "文件管理",
      "导入管理",
      "发布管理",
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
    expect(wrapper.get(".skip-link").attributes("href")).toBe("#main-content");
    expect(wrapper.get("main").attributes("id")).toBe("main-content");
  });
});
