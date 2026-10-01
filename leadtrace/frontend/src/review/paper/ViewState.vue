<script setup lang="ts">
import { computed } from 'vue';
import { t } from '../../i18n';
import { useReviewProgress } from './useReviewProgress';
import type { ViewItem } from '../../v2/workbench';
const props=defineProps<{kind:ViewItem['kind'];entityId:string;compact?:boolean}>();
const state=useReviewProgress();
const item=computed(()=>state?.find(props.kind,props.entityId));
</script>
<template><span v-if="item" class="view-state" :class="{'is-viewed':item.viewed}" :data-viewed="item.viewed"><span>{{ item.viewed ? t('已查看') : t('未查看') }}</span><button v-if="item.viewed && !compact" class="button-quiet" type="button" :aria-label="t('标记未读')" @click.stop="state?.view(kind,entityId,false)">↶</button></span></template>
