<script setup lang="ts">
import { onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import AppSidebar from './components/AppSidebar.vue'
import SourceDrawer from './components/SourceDrawer.vue'
import { useAppStore } from './stores/app'
import { useChatStore } from './stores/chat'
const app = useAppStore(); const chat = useChatStore()
onMounted(async () => {
  app.applyTheme()
  try { await chat.loadSessions() } catch { ElMessage.warning('暂时无法读取历史会话，请检查后端服务') }
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => { if (app.theme === 'system') app.applyTheme() })
})
</script>
<template><div class="application-shell"><AppSidebar /><main class="application-main"><button class="mobile-menu" type="button" aria-label="打开导航" @click="app.sidebarOpen = true">☰</button><router-view /></main><SourceDrawer /></div></template>
