<script setup lang="ts">
import { computed, ref, watch } from 'vue';
import { t } from '../../i18n';
import { ApiError } from '../../api/client';
import { useAuthStore } from '../../auth/store';
import { listCompounds,listEvidence,structureDepictionUrl } from '../../v2/api';
import { saveHighlight,deleteHighlight,type HighlightInput,type DisplayHighlight } from '../../v2/highlights';
import type { Compound,Evidence,PaperWorkspace } from '../../v2/types';
import { useHighlights } from './useHighlights';
import HighlightCards from './HighlightCards.vue';
import EvidenceExcerpt from './EvidenceExcerpt.vue';
const props=defineProps<{workspace:PaperWorkspace;readOnly?:boolean}>();
const emit=defineEmits<{mutated:[version:number];conflict:[]}>();
const state=useHighlights(),auth=useAuthStore();
const compounds=ref<Compound[]>([]),evidence=ref<Evidence[]>([]),loading=ref(false),busy=ref(false),error=ref('');
const editing=ref(false),editingId=ref<string>(),pendingDelete=ref<DisplayHighlight>();
const blank=():HighlightInput=>({compound_id:'',evidence_id:'',role:'study_start',scope:'',rationale:'',review_hint:null,review_status:'draft'});
const form=ref<HighlightInput>(blank());
let editVersion=props.workspace.version,loadGeneration=0,initializing=false;
watch(()=>[form.value.compound_id,form.value.evidence_id,form.value.role,form.value.scope,form.value.rationale,form.value.review_hint],()=>{
 if(!initializing && form.value.review_status==='reviewer_confirmed')form.value.review_status='draft';
},{flush:'sync'});
const depiction=(compoundId:string)=>structureDepictionUrl(compoundId)+'?v='+(state?.version.value??props.workspace.version);
const selectedEvidence=computed(()=>evidence.value.find(x=>x.id===form.value.evidence_id));
async function loadOptions(){
 const request=++loadGeneration,workspaceId=props.workspace.id;loading.value=true;
 try {const [cs,es]=await Promise.all([listCompounds(workspaceId),listEvidence(workspaceId)]);if(request!==loadGeneration)return;compounds.value=cs.items;evidence.value=es.items;}
 catch {if(request===loadGeneration)error.value='标注选项读取失败，请重试。';}
 finally {if(request===loadGeneration)loading.value=false;}
}
watch(()=>[props.workspace.id,props.workspace.version],()=>{void loadOptions();},{immediate:true});
watch(()=>props.workspace.id,()=>{editing.value=false;pendingDelete.value=undefined;error.value='';});
function start(item?:DisplayHighlight){
 if(props.readOnly||busy.value)return;
 error.value='';pendingDelete.value=undefined;editingId.value=item?.id;
 initializing=true;
 form.value=item?{compound_id:item.compound_id,evidence_id:item.evidence_id,role:item.role,scope:item.scope,rationale:item.rationale,review_hint:item.review_hint??null,review_status:item.review_status}:blank();
 initializing=false;
 editVersion=state?.version.value??props.workspace.version;editing.value=true;
}
function failed(reason:unknown){
 if(reason instanceof ApiError&&reason.code==='WORKSPACE_VERSION_CONFLICT'){error.value='标注未保存：工作区已更新。当前输入已保留，请对照最新记录后重新编辑。';emit('conflict');}
 else error.value='标注未保存，请检查来源、必填内容和重复标注。';
}
async function save(){
 if(props.readOnly||busy.value)return;busy.value=true;error.value='';
 try {const result=await saveHighlight(props.workspace.id,editingId.value,{...form.value,scope:form.value.scope.trim(),rationale:form.value.rationale.trim(),review_hint:form.value.review_hint?.trim()||null},editVersion,auth.csrfToken);editing.value=false;await state?.refresh();emit('mutated',result.workspace_version);}
 catch(reason){failed(reason);}finally{busy.value=false;}
}
function requestDelete(item:DisplayHighlight){pendingDelete.value=item;editVersion=state?.version.value??props.workspace.version;}
async function remove(){
 if(!pendingDelete.value||props.readOnly||busy.value)return;busy.value=true;error.value='';
 try{const result=await deleteHighlight(pendingDelete.value.id,editVersion,auth.csrfToken);pendingDelete.value=undefined;await state?.refresh();emit('mutated',result.workspace_version);}
 catch(reason){failed(reason);}finally{busy.value=false;}
}
</script>
<template><section class="highlight-editor" data-highlight-editor>
 <p v-if="state?.loading.value||loading" role="status">{{ t('正在读取文章标注…') }}</p>
 <p v-if="state?.error.value" role="alert">{{ t(state.error.value) }} <button class="button-quiet" type="button" @click="state.refresh">{{ t('重试') }}</button></p>
 <p v-if="error" class="inline-feedback is-error" role="alert">{{ t(error) }} <button v-if="error==='标注选项读取失败，请重试。'" class="button-quiet" @click="loadOptions">{{ t('重试') }}</button></p>
 <HighlightCards v-if="!state?.error.value" :items="state?.items.value??[]" :compounds="compounds" :evidence="evidence" :depiction="depiction" :editable="!readOnly&&!busy&&!editing" @edit="start" @remove="requestDelete" />
 <button v-if="!readOnly&&!editing" class="button-secondary" type="button" data-add-highlight :disabled="busy||loading||state?.loading.value||!!state?.error.value||!compounds.length||!evidence.length" @click="start()">{{ t('添加文章标注') }}</button>
 <p v-if="!readOnly&&!loading&&!evidence.length">{{ t('请先在 Evidence 中保存文章依据，再关联标注。') }}</p>
 <form v-if="editing" data-highlight-form @submit.prevent="save">
 <fieldset :disabled="busy||readOnly"><legend>{{ t('文章级分子标注') }}</legend>
 <label class="form-field">Compound<select v-model="form.compound_id" data-highlight-compound required><option value="" disabled>{{ t('选择 Compound') }}</option><option v-for="c in compounds" :key="c.id" :value="c.id">{{ c.compound_label }} · {{ c.display_name }}</option></select></label>
 <label class="form-field">{{ t('标注类别') }}<select v-model="form.role" data-highlight-role><option value="study_start">{{ t('研究起点') }}</option><option value="paper_selected">{{ t('论文优选') }}</option></select></label>
 <label class="form-field">{{ t('适用范围') }}<input v-model="form.scope" data-highlight-scope required maxlength="512" :placeholder="t('例如：全文，或 Series A 的先导优化')"></label>
 <label class="form-field">{{ t('作者选择理由') }}<textarea v-model="form.rationale" data-highlight-rationale required maxlength="10000" rows="3" :placeholder="t('说明作者为何以此为起点或优先推进，不能仅凭编号或单项活性判断。')"></textarea></label>
 <label class="form-field">{{ t('来源 Evidence') }}<select v-model="form.evidence_id" data-highlight-evidence required><option value="" disabled>{{ t('选择来源证据') }}</option><option v-for="e in evidence" :key="e.id" :value="e.id">{{ t('PDF 页码') }} {{ e.page_number }} · {{ e.caption||e.quoted_text?.slice(0,100)||e.id }}</option></select></label>
 <EvidenceExcerpt v-if="selectedEvidence" :evidence="selectedEvidence" :workspace="workspace" />
 <label class="form-field">{{ t('审核状态') }}<select v-model="form.review_status" data-highlight-status><option value="draft">{{ t('标注待审核') }}</option><option value="reviewer_confirmed">{{ t('标注已确认') }}</option><option value="unresolved">{{ t('标注待解决') }}</option></select></label>
 <label class="form-field">{{ t('核对提示（可选，解决后清空）') }}<textarea v-model="form.review_hint" maxlength="1000"></textarea></label>
 <p>{{ t('查看内容不会自动确认此标注。确认代表你已核对作者陈述与关联结构。') }}</p>
 <div class="editor-actions"><button class="button-primary" type="submit" data-save-highlight>{{ t('保存修改') }}</button><button class="button-quiet" type="button" @click="editing=false">{{ t('取消') }}</button></div>
 </fieldset></form>
 <div v-if="pendingDelete" class="inline-feedback is-warning" role="alert"><p>{{ t('确认删除此文章标注？Compound 与 Evidence 会保留。') }}</p><button class="button-secondary" :disabled="busy||readOnly" type="button" @click="remove">{{ t('确认删除') }}</button><button class="button-quiet" :disabled="busy" type="button" @click="pendingDelete=undefined">{{ t('取消') }}</button></div>
</section></template>
<style scoped>.highlight-editor{margin-top:24px;border-top:1px solid var(--line-strong);padding-top:20px}.highlight-editor fieldset{display:grid;gap:12px;margin-top:16px}.highlight-editor select,.highlight-editor input,.highlight-editor textarea{width:100%}</style>
