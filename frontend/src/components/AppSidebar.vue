<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useAppStore } from '../stores/app'
import { useChatStore } from '../stores/chat'
import { SUBJECT_META } from '../constants'
import type { Subject } from '../types'
const app = useAppStore(); const chat = useChatStore(); const route = useRoute(); const router = useRouter()
const activePath = computed(() => route.path.startsWith('/papers') ? '/papers' : route.path.startsWith('/knowledge') ? '/knowledge' : '/chat')
function newChat() { chat.newSession(); router.push('/chat'); app.sidebarOpen = false }
function openSession(id: string) { router.push(`/chat/${id}`); app.sidebarOpen = false }
function subjectColor(subject: Subject | '') { return subject ? SUBJECT_META[subject].color : '#94a3b8' }
async function editTitle(id: string, current: string) { try { const { value } = await ElMessageBox.prompt('请输入新的会话名称', '重命名会话', { inputValue: current, inputValidator: (v) => !!v.trim() || '标题不能为空' }); await chat.rename(id, value.trim()); ElMessage.success('会话已重命名') } catch { /* cancelled */ } }
async function removeSession(id: string) { try { await ElMessageBox.confirm('删除后会同时移除该会话的全部消息，确定继续吗？', '删除会话', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' }); await chat.remove(id); if (route.params.sessionId === id) router.push('/chat'); ElMessage.success('会话已删除') } catch { /* cancelled */ } }
</script>
<template><aside class="app-sidebar" :class="{ open: app.sidebarOpen }"><div class="brand"><div class="brand-mark">启</div><div><strong>启智学科答疑</strong><span>让每次提问都有依据</span></div></div><button class="new-chat" type="button" @click="newChat"><span>＋</span> 新建对话</button>
<nav class="main-nav" aria-label="主要功能"><router-link to="/chat" :class="{ active: activePath === '/chat' }" @click="app.sidebarOpen = false"><span>问</span>智能答疑</router-link><router-link to="/papers" :class="{ active: activePath === '/papers' }" @click="app.sidebarOpen = false"><span>卷</span>试卷分析</router-link><router-link to="/knowledge" :class="{ active: activePath === '/knowledge' }" @click="app.sidebarOpen = false"><span>库</span>知识库管理</router-link></nav>
<div class="sidebar-section-title"><span>最近对话</span><span v-if="chat.loadingSessions">加载中</span></div><div class="session-list"><button v-for="session in chat.sessions" :key="session.id" class="session-row" :class="{ active: session.id === chat.currentSessionId }" type="button" @click="openSession(session.id)"><span class="subject-dot" :style="{ background: subjectColor(session.subject) }" /><span class="session-copy"><strong>{{ session.title || '新对话' }}</strong><small>{{ session.subject || '未分类' }} · {{ session.message_count }} 条消息</small></span><el-dropdown trigger="click" @click.stop><span class="session-more" @click.stop>···</span><template #dropdown><el-dropdown-menu><el-dropdown-item @click="editTitle(session.id, session.title)">重命名</el-dropdown-item><el-dropdown-item divided @click="removeSession(session.id)">删除</el-dropdown-item></el-dropdown-menu></template></el-dropdown></button><p v-if="!chat.loadingSessions && !chat.sessions.length" class="sidebar-empty">还没有历史对话</p></div>
<div class="sidebar-footer"><label>界面主题</label><el-select :model-value="app.theme" size="small" @change="app.setTheme($event)"><el-option label="跟随系统" value="system" /><el-option label="浅色" value="light" /><el-option label="深色" value="dark" /></el-select></div></aside><div v-if="app.sidebarOpen" class="sidebar-mask" @click="app.sidebarOpen = false" /></template>
