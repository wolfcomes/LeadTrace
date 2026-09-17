import { ref } from "vue";
import type { RouteLocationNormalizedLoaded, Router } from "vue-router";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../auth/store";
import { getPaperWorkspace, listReviewTasks, updateSection } from "../../v2/api";
import type { PaperWorkspace } from "../../v2/types";

export type WorkspaceViewState = "loading" | "ready" | "error" | "not-found";
export type SectionState = "pending" | "completed" | "not_reported";

export function usePaperWorkspace(route: RouteLocationNormalizedLoaded, router: Router) {
  const auth = useAuthStore();
  const state = ref<WorkspaceViewState>("loading");
  const workspace = ref<PaperWorkspace>();
  const requestId = ref<string>();
  const actionError = ref("");
  const concurrencyMessage = ref("");
  const savingSection = ref<string>();
  let loadSequence = 0;

  function routeWorkspaceId(): string | undefined {
    return typeof route.query.workspace === "string" && route.query.workspace
      ? route.query.workspace
      : undefined;
  }

  function routeTargets(paperId: string, id: string | undefined): boolean {
    return String(route.params.paperId ?? "") === paperId && routeWorkspaceId() === id;
  }

  async function resolveWorkspaceId(paperId: string, hinted: string | undefined): Promise<string | undefined> {
    if (typeof hinted === "string" && hinted) return hinted;
    const tasks = await listReviewTasks();
    const candidates = tasks.items.filter((task) => task.paper_id === paperId);
    const task = candidates.find((item) => item.task_status !== "approved") ?? candidates.at(-1);
    if (!task) return undefined;
    return task.workspace_id;
  }

  async function readAggregate(
    id: string,
    paperId: string,
    sequence: number,
    expectedRouteWorkspaceId: string | undefined,
    showLoading = true,
  ): Promise<PaperWorkspace | undefined> {
    if (showLoading) state.value = "loading";
    requestId.value = undefined;
    try {
      const result = await getPaperWorkspace(id);
      if (sequence !== loadSequence || !routeTargets(paperId, expectedRouteWorkspaceId)) return undefined;
      if (result.bibliography.paper_id !== paperId) {
        workspace.value = undefined;
        state.value = "not-found";
        return undefined;
      }
      workspace.value = result;
      state.value = "ready";
      return result;
    } catch (error) {
      if (sequence !== loadSequence || !routeTargets(paperId, expectedRouteWorkspaceId)) return undefined;
      requestId.value = error instanceof ApiError ? error.requestId : undefined;
      state.value = error instanceof ApiError && error.status === 404 ? "not-found" : "error";
      return undefined;
    }
  }

  async function open(): Promise<void> {
    const sequence = ++loadSequence;
    const paperId = String(route.params.paperId ?? "");
    const hintedWorkspaceId = routeWorkspaceId();
    actionError.value = "";
    concurrencyMessage.value = "";
    state.value = "loading";
    requestId.value = undefined;
    try {
      const id = await resolveWorkspaceId(paperId, hintedWorkspaceId);
      if (sequence !== loadSequence) return;
      if (!id) {
        workspace.value = undefined;
        state.value = "not-found";
        return;
      }
      const result = await readAggregate(id, paperId, sequence, hintedWorkspaceId, false);
      if (
        result
        && !hintedWorkspaceId
        && String(route.params.paperId ?? "") === paperId
        && !routeWorkspaceId()
      ) {
        await router.replace({ path: route.path, query: { ...route.query, workspace: id } });
      }
    } catch (error) {
      if (sequence !== loadSequence) return;
      requestId.value = error instanceof ApiError ? error.requestId : undefined;
      state.value = error instanceof ApiError && error.status === 404 ? "not-found" : "error";
    }
  }

  async function reload(target = workspace.value): Promise<PaperWorkspace | undefined> {
    if (!target || !routeTargets(target.bibliography.paper_id, target.id)) return undefined;
    return readAggregate(
      target.id,
      target.bibliography.paper_id,
      ++loadSequence,
      target.id,
      false,
    );
  }

  async function setSectionState(section: string, nextState: SectionState): Promise<void> {
    const current = workspace.value;
    if (!current || savingSection.value || current.state !== "editing" || auth.user?.role !== "reviewer") return;
    savingSection.value = section;
    actionError.value = "";
    concurrencyMessage.value = "";
    try {
      await updateSection(current.id, section, {
        expected_workspace_version: current.version,
        state: nextState,
        note: current.sections.find((item) => item.section_key === section)?.note ?? null,
      }, auth.csrfToken);
      await reload(current);
    } catch (error) {
      if (!routeTargets(current.bibliography.paper_id, current.id)) return;
      requestId.value = error instanceof ApiError ? error.requestId : undefined;
      if (error instanceof ApiError && error.code === "WORKSPACE_VERSION_CONFLICT") {
        const latest = await reload(current);
        if (latest && routeTargets(current.bibliography.paper_id, current.id)) {
          concurrencyMessage.value = "Workspace 已被其他会话更新，已重新载入最新版本；刚才的操作没有覆盖对方修改。";
        }
      } else if (error instanceof ApiError && error.code === "WORKSPACE_READ_ONLY") {
        const latest = await reload(current);
        if (latest && routeTargets(current.bibliography.paper_id, current.id)) {
          actionError.value = "Workspace 已进入只读状态。";
        }
      } else {
        actionError.value = "区段状态未能保存，请稍后重试。";
      }
    } finally {
      savingSection.value = undefined;
    }
  }

  return { state, workspace, requestId, actionError, concurrencyMessage, savingSection, open, reload, setSectionState };
}
