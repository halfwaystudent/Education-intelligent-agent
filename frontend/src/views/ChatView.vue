<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import ChatMessageCard from '../components/ChatMessageCard.vue'
import { getCollections } from '../api'
import { SUBJECTS, SUBJECT_META } from '../constants'
import { useAppStore } from '../stores/app'
import { useChatStore } from '../stores/chat'
import type { CollectionSummary, Subject } from '../types'
const chat = useChatStore(); const app = useAppStore(); const route = useRoute(); const router = useRouter(); const question = ref(''); const messageArea = ref<HTMLElement | null>(null); const collections = ref<CollectionSummary[]>([])
const currentCollection = computed(() => collections.value.find((item) => item.subject === chat.subject))
const stageText = computed(() => ({ routing: '正在理解问题', retrieving: '正在检索课程资料', generating: '正在组织回答' }[chat.stage] || '正在处理'))
async function syncRouteSession() { const id = String(route.params.sessionId || ''); if (id) { try { if (!chat.sessions.length) await chat.loadSessions(); await chat.openSession(id) } catch { ElMessage.error('会话不存在或加载失败'); chat.newSession(); router.replace('/chat') } } else if (chat.currentSessionId) chat.newSession() }
async function send(text = question.value) { const value = text.trim(); if (!value) return; question.value = ''; await chat.send(value); if (chat.currentSessionId && route.params.sessionId !== chat.currentSessionId) router.replace(`/chat/${chat.currentSessionId}`) }
function onKeydown(event: KeyboardEvent) { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); if (!chat.sending) send() } }
watch(() => route.params.sessionId, syncRouteSession, { immediate: true })
watch(() => chat.currentMessages.length, async () => { await nextTick(); if (messageArea.value) messageArea.value.scrollTop = messageArea.value.scrollHeight })
watch(() => chat.currentMessages.at(-1)?.content, async () => { await nextTick(); if (messageArea.value && messageArea.value.scrollHeight - messageArea.value.scrollTop - messageArea.value.clientHeight < 220) messageArea.value.scrollTop = messageArea.value.scrollHeight })
onMounted(async () => { try { collections.value = await getCollections() } catch { /* answer remains usable */ } })
</script>
<template><section class="chat-page"><header class="page-header chat-header"><div><span class="eyebrow">基于课程资料回答</span><h1>智能答疑</h1></div><div class="subject-switch" role="radiogroup" aria-label="选择学科"><button v-for="item in SUBJECTS" :key="item" type="button" :class="{ active: chat.subject === item }" :disabled="chat.subjectLocked && chat.subject !== item" @click="chat.setSubject(item as Subject)"><span :style="{ background: SUBJECT_META[item].color }">{{ SUBJECT_META[item].short }}</span>{{ item }}</button></div></header>
<div ref="messageArea" class="message-area"><div v-if="chat.loadingMessages" class="center-loading"><el-skeleton :rows="4" animated /></div><div v-else-if="!chat.currentMessages.length" class="chat-empty"><div class="empty-orbit"><span :style="{ background: SUBJECT_META[chat.subject].color }">{{ SUBJECT_META[chat.subject].short }}</span></div><span class="eyebrow">{{ chat.subject }}学科助手</span><h2>今天想学习什么？</h2><p>{{ SUBJECT_META[chat.subject].description }}。回答会标明引用来源，方便你核对原始资料。</p><div class="knowledge-status" :class="{ empty: !currentCollection?.document_count }"><span class="status-light" /><template v-if="currentCollection?.document_count">知识库已收录 {{ currentCollection.document_count }} 份资料、{{ currentCollection.chunk_count }} 个知识片段</template><template v-else>当前学科尚未导入资料，仍可提问，但回答可能提示资料不足</template></div><div class="suggestion-grid"><button v-for="suggestion in SUBJECT_META[chat.subject].suggestions" :key="suggestion" type="button" @click="send(suggestion)"><span>↗</span>{{ suggestion }}</button></div></div><div v-else class="messages-column"><ChatMessageCard v-for="(message, index) in chat.currentMessages" :key="String(message.id || index)" :message="message" @source="app.openSource" @retry="send" /></div></div>
<footer class="composer-area"><div v-if="chat.sending" class="generation-status"><span class="pulse" />{{ stageText }}</div><div class="composer"><textarea v-model="question" rows="1" :placeholder="`向${chat.subject}助手提问，Shift + Enter 换行`" :disabled="chat.sending" @keydown="onKeydown" /><button v-if="chat.sending" type="button" class="stop-button" @click="chat.stop">停止</button><button v-else type="button" class="send-button" :disabled="!question.trim()" @click="send()">发送</button></div><p>AI 回答可能存在遗漏，请结合引用资料和教师指导核对。</p></footer></section></template>
