<script setup lang="ts">
import { t } from '../../i18n';
import { profileGroups,targetRoleLabels,type ResearchProfile,type ArticleTarget } from './articleMetadata';
const props=defineProps<{modelValue:ResearchProfile}>();
const emit=defineEmits<{ 'update:modelValue':[value:ResearchProfile] }>();
function add(key:typeof profileGroups[number]['key']) {emit('update:modelValue',{...props.modelValue,[key]:[...(props.modelValue[key]??[]),{label:'',source:'',review_hint:null}]});}
function addTarget() {const target:ArticleTarget={name:'',role:'unknown',source:'',organism:null,gene_symbol:null,uniprot_id:null,ncbi_gene_id:null,review_hint:null};emit('update:modelValue',{...props.modelValue,targets:[...(props.modelValue.targets??[]),target]});}
</script>
<template><section class="research-profile-editor" data-profile-editor>
  <h3>{{t('研究主题信息')}}</h3><p>{{t('只记录来源支持的信息；未填写不等于原文未报告。靶点角色和物种需分别核对。')}}</p>
  <details v-for="group in profileGroups" :key="group.key" class="record-detail" :data-edit-group="group.key">
    <summary>{{t(group.label)}} · {{modelValue[group.key]?.length??0}}</summary>
    <fieldset v-for="(term,index) in modelValue[group.key]" :key="index" class="metadata-grid">
      <legend>{{t(group.label)}} {{index+1}}</legend>
      <label class="form-field">{{t('名称')}}<input v-model="term.label" :list="`metadata-${group.key}`" required maxlength="255" data-term-label></label>
      <label class="form-field">{{t('来源')}}<input v-model="term.source" required maxlength="2000" data-term-source :placeholder="t('例如：PDF 第 1 页，Abstract')"></label>
      <label class="form-field">{{t('核对提示（可选，解决后清空）')}}<input v-model="term.review_hint" maxlength="1000"></label>
      <button type="button" class="button-quiet" @click="modelValue[group.key]?.splice(index,1)">{{t('删除')}}</button>
    </fieldset>
    <datalist :id="`metadata-${group.key}`"><option v-for="value in group.suggestions" :key="value" :value="value" /></datalist>
    <button type="button" class="button-secondary" :data-add-term="group.key" @click="add(group.key)">{{t('添加条目')}}</button>
  </details>
  <details class="record-detail" data-edit-group="targets"><summary>{{t('研究靶点与关联基因')}} · {{modelValue.targets?.length??0}}</summary>
    <fieldset v-for="(target,index) in modelValue.targets" :key="index" class="metadata-grid" data-edit-target>
      <legend>{{t('靶点')}} {{index+1}}</legend>
      <label class="form-field">{{t('靶点名称')}}<input v-model="target.name" required maxlength="255" data-target-name></label>
      <label class="form-field">{{t('研究角色')}}<select v-model="target.role" data-target-role><option v-for="(label,key) in targetRoleLabels" :key="key" :value="key">{{t(label)}}</option></select></label>
      <label class="form-field">{{t('物种')}}<input v-model="target.organism" maxlength="255" data-target-organism></label>
      <label class="form-field">{{t('基因符号')}}<input v-model="target.gene_symbol" maxlength="128" data-target-gene></label>
      <label class="form-field">UniProt ID<input v-model="target.uniprot_id" maxlength="32"></label>
      <label class="form-field">NCBI Gene ID<input v-model="target.ncbi_gene_id" inputmode="numeric" pattern="[1-9][0-9]*" maxlength="20"></label>
      <label class="form-field">{{t('来源')}}<input v-model="target.source" required maxlength="2000" data-target-source></label>
      <label class="form-field">{{t('核对提示（可选，解决后清空）')}}<input v-model="target.review_hint" maxlength="1000"></label>
      <button type="button" class="button-quiet" @click="modelValue.targets?.splice(index,1)">{{t('删除')}}</button>
    </fieldset>
    <button type="button" class="button-secondary" data-add-target @click="addTarget">{{t('添加靶点')}}</button>
  </details>
</section></template>
<style scoped> fieldset {margin:.6rem 0;min-width:0} .record-detail {margin:.7rem 0} </style>
