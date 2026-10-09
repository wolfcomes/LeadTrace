<script setup lang="ts">
import { t } from "../../i18n";
import { computed, onMounted, ref, watch } from "vue";

import { ApiError } from "../../api/client";
import { useAuthStore } from "../../auth/store";
import PdfReviewCanvas from "../../pdf-viewer/PdfReviewCanvas.vue";
import {
  createStructureSourceImage,
  deleteStructureSourceImage,
  listStructureSourceImages,
  retryStructureSourceImage,
  structureDepictionUrl,
  structureSourceImageContentUrl,
} from "../../v2/api";
import type { PaperWorkspace, Structure, StructureSourceImage } from "../../v2/types";

const props = defineProps<{
  compoundId: string;
  paperId: string;
  workspaceVersion: number;
  source: PaperWorkspace["source"];
  structure?: Structure | null;
  readOnly?: boolean;
}>();
const emit = defineEmits<{ mutated: [workspaceVersion: number]; conflict: [] }>();
const auth = useAuthStore();
const images = ref<StructureSourceImage[]>([]);
const localVersion = ref(props.workspaceVersion);
const loading = ref(true);
const busy = ref(false);
const capture = ref(false);
const error = ref("");

watch(() => props.workspaceVersion, (version) => {
  if (version > localVersion.value) localVersion.value = version;
});
watch(() => props.compoundId, () => { void load(); });

const pdfRegions = computed(() => images.value.map((image) => ({
  id: image.id,
  regionKey: image.label ?? `p${image.page_number}`,
  pageNumber: image.page_number,
  ...image.bbox,
  rotation: 0,
})));

function failureMessage(reason: unknown): string {
  if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
    return "Workspace 已更新，请重新载入后再保存。";
  }
  if (reason instanceof ApiError && reason.code === "STRUCTURE_SOURCE_IMAGE_DUPLICATE") {
    return "该 PDF 区域已经保存为此 Compound 的原图。";
  }
  return "Structure Source Image 操作失败，请重试。";
}

function handleMutationFailure(reason: unknown): void {
  if (reason instanceof ApiError && reason.code === "WORKSPACE_VERSION_CONFLICT") {
    emit("conflict");
  }
  error.value = failureMessage(reason);
}

async function load(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const result = await listStructureSourceImages(props.compoundId);
    images.value = result.items;
    localVersion.value = result.workspace_version;
  } catch (reason) {
    error.value = failureMessage(reason);
  } finally {
    loading.value = false;
  }
}

async function captureRegion(region: { pageNumber: number; x0: number; y0: number; x1: number; y1: number }): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await createStructureSourceImage(props.compoundId, {
      expected_workspace_version: localVersion.value,
      source_sha256: props.source.sha256,
      page_number: region.pageNumber,
      bbox: { x0: region.x0, y0: region.y0, x1: region.x1, y1: region.y1 },
      source_context: null,
      label: null,
      reviewer_note: null,
    }, auth.csrfToken);
    images.value = [...images.value, result.source_image];
    localVersion.value = result.workspace_version;
    capture.value = false;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    handleMutationFailure(reason);
  } finally {
    busy.value = false;
  }
}

async function retry(image: StructureSourceImage): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await retryStructureSourceImage(image.id, localVersion.value, auth.csrfToken);
    images.value = images.value.map((item) => item.id === image.id ? result.source_image : item);
    localVersion.value = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    handleMutationFailure(reason);
  } finally {
    busy.value = false;
  }
}

async function remove(image: StructureSourceImage): Promise<void> {
  if (props.readOnly || busy.value) return;
  busy.value = true;
  error.value = "";
  try {
    const result = await deleteStructureSourceImage(image.id, localVersion.value, auth.csrfToken);
    images.value = images.value.filter((item) => item.id !== image.id);
    localVersion.value = result.workspace_version;
    emit("mutated", result.workspace_version);
  } catch (reason) {
    handleMutationFailure(reason);
  } finally {
    busy.value = false;
  }
}

onMounted(load);
</script>

<template>
  <section class="structure-source-images" data-structure-source-images>
    <header class="section-heading compact-heading">
      <div><p class="eyebrow">STRUCTURE SOURCE IMAGES</p><h3>{{ t("分子结构原图") }}</h3></div>
      <button class="button-secondary" data-capture-source-image type="button" :disabled="readOnly || busy" @click="capture = !capture">{{ capture ? t("取消框选") : t("从 PDF 框选") }}</button>
    </header>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ t(error) }}</p>

    <PdfReviewCanvas
      v-if="capture"
      :pdf-url="`/api/v2/papers/${paperId}/source-pdf`"
      :page-count="source.page_count"
      :regions="pdfRegions"
      :read-only="readOnly || busy"
      :selection-mode="true"
      :allow-rotation="false"
      @create-region="captureRegion"
    />

    <p v-if="loading" class="workspace-empty-copy">{{ t("正在读取原图…") }}</p>
    <div v-else class="structure-comparison" data-structure-comparison>
      <article class="evidence-preview-frame">
        <header><strong>{{ t("RDKit 重绘") }}</strong><small>{{ t("数据库当前 Structure") }}</small></header>
        <img v-if="structure?.depiction_asset_id" :src="structureDepictionUrl(compoundId, structure.depiction_asset_id)" :alt="t('{p0} 的 RDKit 图', { p0: compoundId })">
        <p v-else>{{ t("尚无可用的 RDKit 图。") }}</p>
      </article>
      <article v-for="image in images" :key="image.id" class="evidence-preview-frame" :data-source-image-id="image.id">
        <header><strong>Source crop · p{{ image.page_number }}</strong><small>{{ image.label || t("未命名区域") }}</small></header>
        <img v-if="image.crop_status === 'ready'" :src="structureSourceImageContentUrl(image.id)" :alt="t('第 {p0} 页的结构原图', { p0: image.page_number })">
        <p v-else-if="image.crop_status === 'failed'">{{ t("生成失败；PDF locator 已保留。") }}</p>
        <p v-else>{{ t("正在生成 crop…") }}</p>
        <p v-if="image.source_context" data-source-context>{{ image.source_context }}</p>
        <a v-if="image.crop_status === 'ready'" data-open-source-crop :href="structureSourceImageContentUrl(image.id)" target="_blank" rel="noopener">{{ t("查看原图大图 ↗") }}</a>
        <footer v-if="!readOnly" class="editor-actions">
          <button v-if="image.crop_status === 'failed'" class="button-secondary" data-retry-crop type="button" :disabled="busy" @click="retry(image)">{{ t("重试 crop") }}</button>
          <button class="button-quiet" type="button" :disabled="busy" @click="remove(image)">{{ t("删除") }}</button>
        </footer>
      </article>
    </div>
  </section>
</template>
