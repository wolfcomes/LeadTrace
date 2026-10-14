<script setup lang="ts">
import { t } from '../../i18n';
import ArticleEvidenceEditor from './ArticleEvidenceEditor.vue';
import { profileGroups,targetRoleLabels,modalityChoices,modalityLabel,revealInvalidField,type ResearchProfile,type ArticleTarget,type ModalityChoice } from './articleMetadata';
const props=defineProps<{modelValue:ResearchProfile}>();
const initialModalities=JSON.parse(JSON.stringify(props.modelValue.modalities??[])) as NonNullable<ResearchProfile['modalities']>;
function needsExplanation(term:NonNullable<ResearchProfile['modalities']>[number]) {return ['其他','待明确'].includes(term.label) && !initialModalities.some(existing=>existing.label===term.label && existing.source===term.source && !existing.review_hint);}
const emit=defineEmits<{ 'update:modelValue':[value:ResearchProfile] }>();
function add(key:typeof profileGroups[number]['key']) {emit('update:modelValue',{...props.modelValue,[key]:[...(props.modelValue[key]??[]),{label:'',source:'',review_hint:null}]});}
function addTarget() {const target:ArticleTarget={name:'',role:'unknown',source:'',organism:null,gene_symbol:null,uniprot_id:null,ncbi_gene_id:null,review_hint:null};emit('update:modelValue',{...props.modelValue,targets:[...(props.modelValue.targets??[]),target]});}
function toggleModality(choice:ModalityChoice,event:Event) {
  const selected=(event.target as HTMLInputElement).checked;
  const modalities=selected?[...(props.modelValue.modalities??[]),{label:choice,source:'',review_hint:null}]:(props.modelValue.modalities??[]).filter(term=>modalityLabel(term.label)!==choice);
  emit('update:modelValue',{...props.modelValue,modalities});
}
</script>
<template><section class="research-profile-editor" data-profile-editor @invalid.capture="revealInvalidField">
  <h3>{{t('研究主题信息')}}</h3><p class="editor-guidance">{{t('只记录来源支持的信息；未填写不等于原文未报告。靶点角色和物种需分别核对。')}}</p>
  <details v-for="group in profileGroups" :key="group.key" class="record-detail" :data-edit-group="group.key">
    <summary>{{t(group.label)}} · {{modelValue[group.key]?.length??0}}</summary>
    <div v-if="group.key==='modalities'" class="modality-choices" role="group" :aria-label="t('作用模态')"><label v-for="choice in modalityChoices" :key="choice"><input type="checkbox" data-modality-choice :value="choice" :checked="modelValue.modalities?.some(term=>modalityLabel(term.label)===choice)??false" @change="toggleModality(choice,$event)">{{t(choice)}}</label></div>
    <fieldset v-for="(term,index) in modelValue[group.key]" :key="index" class="metadata-entry">
      <legend>{{t(group.label)}} {{index+1}}</legend>
      <template v-if="group.key==='modalities'"><strong>{{t(modalityLabel(term.label)??term.label)}}</strong><p v-if="modalityLabel(term.label)!==term.label" class="legacy-wording">{{t('原始词条')}}：{{term.label}}</p><label v-if="!modalityLabel(term.label)" class="form-field">{{t('旧词条，待选择')}}<select v-model="term.label" data-legacy-modality><option :value="term.label" disabled>{{term.label}}</option><option v-for="choice in modalityChoices" :key="choice" :value="choice">{{t(choice)}}</option></select></label></template>
      <label v-else class="form-field">{{t('名称')}}<textarea v-model="term.label" required maxlength="255" rows="2" data-term-label></textarea></label>
      <details class="entry-evidence" :open="!term.source"><summary>{{t('依据与说明')}}<span v-if="term.review_hint"> · ⚠ {{t('需核对')}}</span></summary><label class="form-field">{{t('来源')}}<textarea v-model="term.source" required maxlength="2000" rows="3" data-term-source :placeholder="t('例如：PDF 第 1 页，Abstract')"></textarea></label><label class="form-field">{{t(group.key==='modalities' && needsExplanation(term)?'分类说明（必填）':'核对提示（可选，解决后清空）')}}<textarea v-model="term.review_hint" data-term-hint :required="group.key==='modalities' && needsExplanation(term)" maxlength="1000" rows="2"></textarea></label></details>
      <ArticleEvidenceEditor v-model="term.evidence" /><button type="button" class="button-quiet" @click="modelValue[group.key]?.splice(index,1)">{{t('删除')}}</button>
    </fieldset>
    <button v-if="group.key!=='modalities'" type="button" class="button-secondary" :data-add-term="group.key" @click="add(group.key)">{{t('添加条目')}}</button>
  </details>
  <details class="record-detail" data-edit-group="targets"><summary>{{t('研究靶点与关联基因')}} · {{modelValue.targets?.length??0}}</summary>
    <fieldset v-for="(target,index) in modelValue.targets" :key="index" class="metadata-entry" data-edit-target>
      <legend>{{t('靶点')}} {{index+1}}</legend><div class="target-grid">
      <label class="form-field">{{t('靶点名称')}}<input v-model="target.name" required maxlength="255" data-target-name></label>
      <label class="form-field">{{t('研究角色')}}<select v-model="target.role" data-target-role><option v-for="(label,key) in targetRoleLabels" :key="key" :value="key">{{t(label)}}</option></select></label>
      <label class="form-field">{{t('物种')}}<input v-model="target.organism" maxlength="255" data-target-organism></label>
      <label class="form-field">{{t('基因符号')}}<input v-model="target.gene_symbol" maxlength="128" data-target-gene></label></div>
      <details class="entry-evidence" :open="!target.source"><summary>{{t('编号与依据')}}<span v-if="target.review_hint"> · ⚠ {{t('需核对')}}</span></summary><div class="target-grid"><label class="form-field">UniProt ID<input v-model="target.uniprot_id" maxlength="32"></label><label class="form-field">NCBI Gene ID<input v-model="target.ncbi_gene_id" inputmode="numeric" pattern="[1-9][0-9]*" maxlength="20"></label></div>
      <label class="form-field">{{t('来源')}}<textarea v-model="target.source" required maxlength="2000" rows="3" data-target-source></textarea></label>
      <label class="form-field">{{t('核对提示（可选，解决后清空）')}}<textarea v-model="target.review_hint" maxlength="1000" rows="2"></textarea></label></details>
      <ArticleEvidenceEditor v-model="target.evidence" /><button type="button" class="button-quiet" @click="modelValue.targets?.splice(index,1)">{{t('删除')}}</button>
    </fieldset>
    <button type="button" class="button-secondary" data-add-target @click="addTarget">{{t('添加靶点')}}</button>
  </details>
</section></template>
<style scoped>.metadata-entry{margin:.75rem 0;padding:.85rem;min-width:0;border:1px solid var(--line);border-radius:6px}.record-detail{margin:.7rem 0}.target-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:.7rem}.entry-evidence{margin:.6rem 0}.entry-evidence summary{cursor:pointer;color:var(--ink-muted);margin-bottom:.5rem}.modality-choices{display:flex;gap:.6rem 1rem;flex-wrap:wrap;margin:.75rem 0}.modality-choices label{display:flex;gap:.35rem;align-items:center}.modality-choices input{width:auto}.legacy-wording,.editor-guidance{font-size:.85rem;color:var(--ink-muted)}.form-field{margin:.5rem 0;min-width:0}.form-field textarea{resize:vertical;width:100%;box-sizing:border-box} @media(max-width:600px){.target-grid{grid-template-columns:1fr}}</style>
