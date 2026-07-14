<script setup lang="ts">
import { computed } from 'vue'
import type { RetrievedChunk } from '../types'
import { cleanDisplayText, sanitizeQuestionHtml } from '../utils/render'
const props = withDefaults(defineProps<{ chunk: RetrievedChunk; index?: number; diagnostic?: boolean }>(), { index: 0, diagnostic: false })
defineEmits<{ select: [chunk: RetrievedChunk] }>()
const meta = computed(() => props.chunk.metadata || {})
const score = computed(() => typeof props.chunk.score === 'number' ? props.chunk.score : 0)
const scorePercent = computed(() => `${Math.max(0, Math.min(100, score.value * 100))}%`)
const previewHtml = computed(() => meta.value.display_html ? sanitizeQuestionHtml(String(meta.value.display_html)) : '')
const previewText = computed(() => cleanDisplayText(props.chunk.content || '').slice(0, props.diagnostic ? 720 : 260))
</script>
<template><article class="chunk-card" role="button" tabindex="0" @click="$emit('select', chunk)" @keydown.enter="$emit('select', chunk)">
<header class="chunk-card__head"><span class="rank-badge">{{ index + 1 }}</span><div class="chunk-card__source"><strong>{{ meta.file_name || '未知资料' }}</strong><span>{{ meta.page ? `第 ${meta.page} 页` : '页码未知' }}<template v-if="meta.section_title"> · {{ meta.section_title }}</template></span></div><span v-if="typeof chunk.score === 'number'" class="score-text">{{ chunk.score.toFixed(3) }}</span></header>
<div v-if="diagnostic && typeof chunk.score === 'number'" class="score-track"><span :style="{ width: scorePercent }" /></div><div v-if="previewHtml" class="question-preview" v-html="previewHtml" /><p v-else class="chunk-preview">{{ previewText || '暂无可展示文本' }}</p>
<footer v-if="diagnostic" class="chunk-card__meta"><span>题号：{{ meta.question_no || '-' }}</span><span>题型：{{ meta.question_type || '-' }}</span><code>{{ meta.chunk_id || '-' }}</code></footer></article></template>
