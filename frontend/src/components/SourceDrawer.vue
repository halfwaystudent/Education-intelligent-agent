<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useAppStore } from '../stores/app'
import { cleanDisplayText, sanitizeQuestionHtml } from '../utils/render'
const app = useAppStore(); const mobile = ref(window.innerWidth < 760); const update = () => { mobile.value = window.innerWidth < 760 }
onMounted(() => window.addEventListener('resize', update)); onBeforeUnmount(() => window.removeEventListener('resize', update))
const meta = computed(() => app.selectedChunk?.metadata || {}); const image = computed(() => String(meta.value.question_image_url || '')); const html = computed(() => meta.value.display_html ? sanitizeQuestionHtml(String(meta.value.display_html)) : ''); const text = computed(() => cleanDisplayText(app.selectedChunk?.content || ''))
</script>
<template><el-drawer v-model="app.sourceOpen" :direction="mobile ? 'btt' : 'rtl'" :size="mobile ? '82%' : '460px'" title="引用资料详情" append-to-body><div v-if="app.selectedChunk" class="source-drawer"><div class="source-heading"><span class="eyebrow">来源资料</span><h3>{{ meta.file_name || '未知资料' }}</h3><p>{{ meta.page ? `第 ${meta.page} 页` : '页码未知' }}<template v-if="meta.section_title"> · {{ meta.section_title }}</template></p></div>
<el-image v-if="image" class="source-image" :src="image" :preview-src-list="[image]" fit="contain" preview-teleported><template #error><div class="image-error">原题图片加载失败</div></template></el-image><div v-else-if="html" class="question-detail" v-html="html" /><div v-else class="source-text">{{ text || '暂无可展示内容' }}</div>
<dl class="source-metadata"><div><dt>题号</dt><dd>{{ meta.question_no || '-' }}</dd></div><div><dt>题型</dt><dd>{{ meta.question_type || '-' }}</dd></div><div><dt>Chunk ID</dt><dd><code>{{ meta.chunk_id || '-' }}</code></dd></div><div v-if="typeof app.selectedChunk.score === 'number'"><dt>匹配分数</dt><dd>{{ app.selectedChunk.score.toFixed(4) }}</dd></div></dl></div></el-drawer></template>
