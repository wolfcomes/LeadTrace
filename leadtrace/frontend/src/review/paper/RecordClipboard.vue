<script setup lang="ts">
import { usePendingEdit } from "./usePendingEdits";
import { computed, ref, watch } from 'vue';
import { ApiError } from '../../api/client';
import { useAuthStore } from '../../auth/store';
import { locale } from '../../i18n';
import { pasteRecord } from './clipboardApi';

const props = defineProps<{ kind: 'compound' | 'lineage'; workspaceId: string; workspaceVersion: number; source?: { id: string; label: string }; records: { label: string; name?: string | null }[]; disabled?: boolean }>();
const emit = defineEmits<{ pasted: [entityId: string, workspaceVersion: number]; conflict: [] }>();
const auth = useAuthStore();
const copied = ref<{ id: string; label: string }>();
const preview = ref(false), busy = ref(false), label = ref(''), name = ref(''), error = ref('');
const tr = (zh: string, en: string) => locale.value === 'en' ? en : zh;
const duplicateLabel = computed(() => props.records.some(record => record.label.trim() === label.value.trim()));
const duplicateName = computed(() => !!name.value.trim() && props.records.some(record => record.name?.trim().toLocaleLowerCase() === name.value.trim().toLocaleLowerCase()));
const blocked = computed(() => props.disabled || busy.value || !label.value.trim() || (props.kind === 'compound' && duplicateLabel.value));
watch(() => [props.workspaceId, props.kind], () => { copied.value = undefined; preview.value = false; });
function copy(): void { if (props.disabled || busy.value || !props.source) return; copied.value = { ...props.source }; preview.value = false; error.value = ''; }
function openPaste(): void { if (props.disabled || busy.value || !copied.value) return; label.value = ''; name.value = ''; error.value = ''; preview.value = true; }
async function paste(): Promise<void> {
  if (blocked.value || !copied.value) return;
  busy.value = true; error.value = '';
  try {
    const result = await pasteRecord(props.workspaceId, props.kind, { source_id: copied.value.id, expected_workspace_version: props.workspaceVersion, label: label.value.trim(), ...(props.kind === 'compound' ? { display_name: name.value.trim() || null } : {}) }, auth.csrfToken);
    preview.value = false; emit('pasted', result.entity_id, result.workspace_version);
  } catch (reason) {
    if (reason instanceof ApiError && reason.code === 'WORKSPACE_VERSION_CONFLICT') { emit('conflict'); error.value = tr('内容已更新，请刷新后重新粘贴。', 'Content changed. Refresh before pasting again.'); }
    else if (reason instanceof ApiError && reason.code === 'COMPOUND_LABEL_CONFLICT') error.value = tr('该 Compound 编号已存在，请修改。', 'This Compound identifier already exists. Choose another.');
    else error.value = tr('粘贴未成功，源条目可能已删除。请刷新后重试。', 'Paste failed; the source may have been deleted. Refresh and retry.');
  } finally { busy.value = false; }
}
usePendingEdit(() => preview.value || busy.value);
</script>
<template>
  <section class="record-clipboard" :data-clipboard-kind="kind">
    <div class="editor-actions">
      <button type="button" class="button-secondary" data-copy-record :disabled="disabled || busy || !source" @click="copy">{{ tr('复制当前条目', 'Copy current record') }}</button>
      <button type="button" class="button-secondary" data-paste-record :disabled="disabled || busy || !copied" @click="openPaste">{{ tr('粘贴为新条目', 'Paste as new record') }}</button>
      <span v-if="copied" role="status">{{ tr('已复制：', 'Copied: ') }}{{ copied.label }}</span>
    </div>
    <form v-if="preview" class="inline-create-form" data-paste-preview @submit.prevent="paste">
      <p>{{ kind === 'compound' ? tr('复制结构、来源图片和 Activity；新结构为 Draft，不复制 Lineage 成员或文章标注。', 'Copies structure, source images and Activities. Structure starts as Draft; Lineage membership and article highlights are excluded.') : tr('复用 Compound 和 Evidence，复制成员及 Edge；新 Edge 为 Draft。', 'Reuses Compounds and Evidence; copies members and Edges, with new Edges set to Draft.') }}</p>
      <label class="form-field">{{ kind === 'compound' ? 'Compound label' : 'Lineage label' }}<input v-model="label" data-paste-label class="form-control" required maxlength="255" :disabled="busy || disabled"></label>
      <p v-if="duplicateLabel && label.trim()" data-clipboard-label-warning role="status">{{ kind === 'compound' ? tr('该 Compound 编号已存在，请修改后保存。', 'This Compound identifier already exists. Change it before saving.') : tr('已有同名 Lineage，请确认是否继续。', 'A Lineage with this name already exists. Check before continuing.') }}</p>
      <label v-if="kind === 'compound'" class="form-field">{{ tr('显示名称', 'Display name') }}<input v-model="name" data-paste-name class="form-control" maxlength="512" :disabled="busy || disabled"></label>
      <p v-if="duplicateName" data-clipboard-name-warning role="status">{{ tr('已有相同显示名称；可以保存，请核对是否重复。', 'This display name already exists. You may save; check for duplication.') }}</p>
      <div class="editor-actions"><button type="submit" data-confirm-paste class="button-primary" :disabled="blocked">{{ tr('创建独立条目', 'Create independent record') }}</button><button type="button" class="button-quiet" :disabled="busy" @click="preview = false">{{ tr('取消', 'Cancel') }}</button></div>
    </form>
    <p v-if="error" class="inline-feedback is-error" role="alert">{{ error }}</p>
  </section>
</template>
<style scoped>
.record-clipboard .inline-create-form {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(min(100%, 16rem), 1fr));
  gap: 0.75rem;
}
.record-clipboard .inline-create-form > p,
.record-clipboard .inline-create-form > .editor-actions {
  grid-column: 1 / -1;
}
.record-clipboard .form-field,
.record-clipboard .form-control {
  min-width: 0;
}
</style>
