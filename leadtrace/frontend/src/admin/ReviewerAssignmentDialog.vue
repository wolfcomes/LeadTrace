<script setup lang="ts">
import { t, locale } from "../i18n";
import { X } from "lucide-vue-next";
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from "vue";

import { ApiError } from "../api/client";
import { useAuthStore } from "../auth/store";
import { assignPaper } from "../v2/api";
import type { AssignmentResponse, PaperCatalogRow } from "../v2/types";
import { fetchAdminUsers, type AdminUser } from "./api";


const props = defineProps<{ paper: PaperCatalogRow }>();
const emit = defineEmits<{
  close: [];
  assigned: [result: AssignmentResponse, reviewerName: string];
}>();

const auth = useAuthStore();
const reviewers = ref<AdminUser[]>([]);
const reviewerId = ref("");
const loading = ref(true);
const saving = ref(false);
const errorMessage = ref("");
const requestId = ref<string>();
const dialogElement = ref<HTMLElement>();
const reviewerSelect = ref<HTMLSelectElement>();
let previousFocus: HTMLElement | null = null;

const enabledReviewers = computed(() => reviewers.value.filter(
  (reviewer) => reviewer.role === "reviewer" && reviewer.is_enabled,
));

async function loadReviewers(): Promise<void> {
  loading.value = true;
  errorMessage.value = "";
  try {
    reviewers.value = await fetchAdminUsers();
    reviewerId.value = enabledReviewers.value[0]?.id ?? "";
  } catch (error) {
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    errorMessage.value = "无法读取 Reviewer 列表，请稍后重试。";
  } finally {
    loading.value = false;
  }
}

async function submit(): Promise<void> {
  if (!reviewerId.value || saving.value) return;
  saving.value = true;
  errorMessage.value = "";
  requestId.value = undefined;
  try {
    const result = await assignPaper(props.paper.id, reviewerId.value, auth.csrfToken);
    const reviewer = enabledReviewers.value.find((item) => item.id === reviewerId.value);
    emit("assigned", result, reviewer?.display_name ?? "未知 Reviewer");
  } catch (error) {
    requestId.value = error instanceof ApiError ? error.requestId : undefined;
    if (error instanceof ApiError && error.code === "ACTIVE_ASSIGNMENT_EXISTS") {
      errorMessage.value = "该文章已有活动分配，请刷新目录后再试。";
    } else if (error instanceof ApiError && error.code === "PAPER_SOURCE_UNVERIFIED") {
      errorMessage.value = "Source PDF 未通过完整性检查，暂时不能分配。";
    } else {
      errorMessage.value = "分配失败，请稍后重试。";
    }
  } finally {
    saving.value = false;
  }
}

function close(): void {
  emit("close");
}

function handleKeydown(event: KeyboardEvent): void {
  if (event.key === "Escape") {
    event.preventDefault();
    close();
    return;
  }
  if (event.key !== "Tab" || !dialogElement.value) return;
  const focusable = Array.from(dialogElement.value.querySelectorAll<HTMLElement>(
    "button:not([disabled]), select:not([disabled]), input:not([disabled]), a[href], [tabindex]:not([tabindex='-1'])",
  ));
  if (focusable.length === 0) {
    event.preventDefault();
    dialogElement.value.focus();
    return;
  }
  const first = focusable[0];
  const last = focusable[focusable.length - 1];
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault();
    last?.focus();
  } else if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault();
    first?.focus();
  }
}

onMounted(async () => {
  previousFocus = document.activeElement instanceof HTMLElement
    ? document.activeElement
    : null;
  await loadReviewers();
  await nextTick();
  (reviewerSelect.value ?? dialogElement.value)?.focus();
});

onBeforeUnmount(() => {
  previousFocus?.focus();
});
</script>

<template>
  <div class="dialog-backdrop" data-assignment-dialog @click.self="close">
    <section
      ref="dialogElement"
      class="assignment-dialog panel"
      role="dialog"
      aria-modal="true"
      aria-labelledby="assignment-title"
      tabindex="-1"
      @keydown="handleKeydown"
    >
      <header>
        <div>
          <p class="eyebrow">REVIEW ASSIGNMENT</p>
          <h2 id="assignment-title">{{ t("分配 Reviewer") }}</h2>
        </div>
        <button class="icon-button" type="button" :title="t('关闭')" :aria-label="t('关闭')" @click="close">
          <X :size="18" aria-hidden="true" />
        </button>
      </header>
      <div class="assignment-paper">
        <code>{{ paper.paper_key }}</code>
        <strong>{{ paper.title }}</strong>
      </div>
      <form data-assignment-form @submit.prevent="submit">
        <label class="form-field"> Reviewer <select ref="reviewerSelect" v-model="reviewerId" required :disabled="loading || saving">
            <option value="" disabled>{{ t(loading ? "正在读取…" : "请选择 Reviewer") }}</option>
            <option
              v-for="reviewer in enabledReviewers"
              :key="reviewer.id"
              data-reviewer-option
              :value="reviewer.id"
            >
              {{ reviewer.display_name }} · {{ reviewer.username }}
            </option>
          </select>
        </label>
        <p v-if="!loading && enabledReviewers.length === 0 && !errorMessage" class="inline-feedback is-error" role="alert"> {{ t("当前没有可用的 Reviewer 账号。") }} </p>
        <p v-if="errorMessage" class="inline-feedback is-error" role="alert">
          {{ t(errorMessage) }}
          <small v-if="requestId">{{ t("请求编号 ·") }} {{ requestId }}</small>
        </p>
        <div class="dialog-actions">
          <button class="button-secondary" type="button" :disabled="saving" @click="close">{{ t("取消") }}</button>
          <button class="button-primary" type="submit" :disabled="loading || saving || !reviewerId">
            {{ t(saving ? "正在分配…" : "确认分配") }}
          </button>
        </div>
      </form>
    </section>
  </div>
</template>
