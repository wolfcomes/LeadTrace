<script setup lang="ts">
import { ref } from 'vue';
import { t } from '../../i18n';
import { ApiError, apiRequest } from '../../api/client';
import { useAuthStore } from '../../auth/store';
import { paperWorkspaceSchema, type PaperWorkspace } from '../../v2/types';
import type { PdbReference } from '../../v2/workbench';
import ArticleMetadata from './ArticleMetadata.vue';
const props = defineProps<{workspace:PaperWorkspace;readOnly?:boolean}>();
const emit=defineEmits<{mutated:[version:number];conflict:[]}>();
const auth=useAuthStore();
const editing=ref(false), busy=ref(false), error=ref('');
const draft=ref({...props.workspace.bibliography,pdb_references:[] as PdbReference[]});
let editVersion=props.workspace.version;
function start() { draft.value=JSON.parse(JSON.stringify({...props.workspace.bibliography,pdb_references:props.workspace.bibliography.pdb_references??[]})); editVersion=props.workspace.version; editing.value=true; }
function addPdb() { draft.value.pdb_references.push({pdb_id:'',usage:'unknown',source_page:null,source_context:null,compound_label:null,review_hint:null}); }
async function save() {
  if(props.readOnly||busy.value)return;
  busy.value=true;error.value='';
  const {paper_id:_id,paper_key:_key,...fields}=draft.value;
  try {
    const result=await apiRequest(`/api/v2/workspaces/${props.workspace.id}/bibliography`,paperWorkspaceSchema,{method:'PATCH',csrfToken:auth.csrfToken,body:{...fields,abstract:fields.abstract||null,abstract_source:fields.abstract_source||null,expected_workspace_version:editVersion}});
    editing.value=false;emit('mutated',result.version);
  } catch(reason) {
    if(reason instanceof ApiError&&reason.code==='WORKSPACE_VERSION_CONFLICT') {error.value='文章信息已更新，请保留当前输入并重新核对。';emit('conflict');}
    else error.value='文章信息未保存，请检查 PDB 编号、页码及必填字段。';
  } finally {busy.value=false;}
}
</script>
<template><section>
  <header class="section-heading"><h2>{{ t('文章信息') }}</h2><button class="button-secondary" type="button" :disabled="readOnly||busy" data-edit-bibliography @click="start">{{ t('编辑基础信息') }}</button></header>
  <p v-if="error" role="alert" class="inline-feedback is-error">{{ t(error) }}</p>
  <details v-if="!editing" class="record-detail" data-bibliography-detail open>
    <summary>{{ t('查看文章信息与摘要') }}</summary>
    <dl class="workspace-bibliography"><div><dt>{{ t('标题') }}</dt><dd>{{ workspace.bibliography.title }}</dd></div><div><dt>{{ t('期刊') }}</dt><dd>{{ workspace.bibliography.journal }} · {{ workspace.bibliography.publication_year }}</dd></div><div><dt>DOI</dt><dd>{{ workspace.bibliography.doi||t('未报告') }}</dd></div><div><dt>{{ t('卷 / 期') }}</dt><dd>{{ workspace.bibliography.volume }} / {{ workspace.bibliography.issue }}</dd></div></dl>
    <ArticleMetadata :metadata="workspace.bibliography" />
  </details>
  <form v-else class="bibliography-edit-form" @submit.prevent="save">
    <label class="form-field">{{ t('标题') }}<input v-model="draft.title" required maxlength="1024"></label>
    <div class="metadata-grid"><label class="form-field">{{ t('期刊') }}<input v-model="draft.journal" required maxlength="255"></label><label class="form-field">{{ t('年份') }}<input v-model.number="draft.publication_year" type="number" min="1000" max="9999" required></label><label class="form-field">Volume<input v-model="draft.volume" required maxlength="64"></label><label class="form-field">Issue<input v-model="draft.issue" required maxlength="64"></label><label class="form-field">DOI<input v-model="draft.doi" maxlength="255" placeholder="10.1021/…"></label></div>
    <label class="form-field">Abstract<textarea v-model="draft.abstract" data-abstract-input rows="7" maxlength="30000" :placeholder="t('按来源填写原文摘要；不要把 AI 总结作为 Abstract。')"></textarea></label>
    <label class="form-field">{{ t('摘要来源') }}<input v-model="draft.abstract_source" maxlength="2000" :placeholder="t('例如：PDF 第 1 页，Abstract')"></label>
    <h3>{{ t('PDB 引用') }}</h3><p>{{ t('记录文章实际提到的结构编号及用途；三字符配体代码不是 PDB ID。') }}</p>
    <fieldset v-for="(entry,index) in draft.pdb_references" :key="index" class="metadata-grid"><legend>PDB {{ index+1 }}</legend>
      <label class="form-field">PDB ID<input v-model="entry.pdb_id" data-pdb-id required maxlength="12" placeholder="1ABC / pdb_00001abc"></label>
      <label class="form-field">{{ t('用途') }}<select v-model="entry.usage"><option value="unknown">{{ t('用途待核对') }}</option><option value="this_work">{{ t('本文结构') }}</option><option value="cited_structure">{{ t('引用结构') }}</option></select></label>
      <label class="form-field">{{ t('PDF 页码') }}<input v-model.number="entry.source_page" type="number" min="1" :max="workspace.source.page_count" @change="entry.source_page = Number(entry.source_page) || null"></label>
      <label class="form-field">{{ t('关联 Compound 编号') }}<input v-model="entry.compound_label" maxlength="255" :placeholder="t('仅在来源明确配对时填写')"></label>
      <label class="form-field">{{ t('来源上下文') }}<textarea v-model="entry.source_context" maxlength="2000" :placeholder="t('例如：引用既有受体结构用于 docking；不是本文新解析结构。')"></textarea></label>
      <label class="form-field">{{ t('核对提示（可选，解决后清空）') }}<input v-model="entry.review_hint" maxlength="1000"></label>
      <button type="button" class="button-quiet" @click="draft.pdb_references.splice(index,1)">{{ t('删除') }}</button>
    </fieldset>
    <button type="button" class="button-secondary" data-add-pdb @click="addPdb">{{ t('添加 PDB ID') }}</button>
    <div class="editor-actions"><button class="button-primary" type="submit" data-save-bibliography :disabled="busy">{{ t('保存修改') }}</button><button type="button" class="button-quiet" :disabled="busy" @click="editing=false">{{ t('取消') }}</button></div>
  </form>
</section></template>
