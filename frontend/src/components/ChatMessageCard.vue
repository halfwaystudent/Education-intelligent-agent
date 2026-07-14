<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { CONFIDENCE_META, ROUTE_LABELS } from '../constants'
import type { ChatMessage, RetrievedChunk } from '../types'
import MarkdownContent from './MarkdownContent.vue'
import RetrievedChunkCard from './RetrievedChunkCard.vue'
const props = defineProps<{ message: ChatMessage }>(); const emit = defineEmits<{ source: [chunk: RetrievedChunk]; retry: [question: string] }>()
const expanded = ref(false); const isLong = computed(() => props.message.content.length > 900); const confidence = computed(() => CONFIDENCE_META[props.message.confidence || ''])
async function copyAnswer() { await navigator.clipboard.writeText(props.message.content); ElMessage.success('回答已复制') }
function openCitation(chunkId: string) { const chunk = props.message.retrieved_chunks?.find((item) => String(item.metadata?.chunk_id || '') === chunkId); if (chunk) emit('source', chunk) }
</script>
<template><div class="message-row" :class="message.role"><div class="message-avatar">{{ message.role === 'user' ? '我' : '智' }}</div><article class="message-card" :class="{ 'is-error': message.error }">
<template v-if="message.role === 'user'"><p class="user-text">{{ message.content }}</p></template><template v-else>
<div v-if="message.route || message.confidence" class="answer-meta"><el-tag v-if="message.route" effect="plain" size="small">{{ ROUTE_LABELS[message.route] || message.route }}</el-tag><el-tooltip :content="confidence.description" placement="top"><el-tag :type="confidence.type" effect="light" size="small">{{ confidence.label }}</el-tag></el-tooltip></div>
<div class="answer-content" :class="{ collapsed: isLong && !expanded }"><MarkdownContent :content="message.content || (message.streaming ? '正在思考…' : '')" /></div><button v-if="isLong" class="text-button" type="button" @click="expanded = !expanded">{{ expanded ? '收起回答' : '展开完整回答' }}</button><span v-if="message.streaming" class="streaming-dot" aria-label="正在生成" />
<el-alert v-if="message.error" :title="message.error" type="error" :closable="false" show-icon class="message-error" />
<div v-if="message.citations?.length" class="citation-list"><button v-for="(citation, index) in message.citations" :key="citation.chunk_id" type="button" class="citation-chip" @click="openCitation(citation.chunk_id)"><span>[{{ index + 1 }}]</span>{{ citation.file_name || '未知资料' }}<template v-if="citation.page"> · 第{{ citation.page }}页</template></button></div>
<div class="answer-actions"><button type="button" class="icon-action" @click="copyAnswer">复制</button><button v-if="message.retry_question" type="button" class="icon-action" @click="$emit('retry', message.retry_question)">重试</button></div>
<details v-if="message.retrieved_chunks?.length" class="retrieval-details"><summary>查看检索依据（{{ message.retrieved_chunks.length }}）</summary><RetrievedChunkCard v-for="(chunk, index) in message.retrieved_chunks.slice(0, 5)" :key="String(chunk.metadata?.chunk_id || index)" :chunk="chunk" :index="index" @select="$emit('source', $event)" /></details>
</template></article></div></template>
