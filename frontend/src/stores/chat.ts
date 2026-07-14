import { defineStore } from 'pinia'
import { deleteSession, getSessionMessages, getSessions, renameSession, streamChat } from '../api'
import { SUBJECT_META } from '../constants'
import type { ChatMessage, ChatRequest, ChatSession, Confidence, RetrievedChunk, Subject } from '../types'
const DRAFT_KEY = '__draft__'
export const useChatStore = defineStore('chat', {
  state: () => ({
    sessions: [] as ChatSession[], messages: {} as Record<string, ChatMessage[]>, currentSessionId: '',
    subject: (localStorage.getItem('education_subject') as Subject) || '数学', loadingSessions: false,
    loadingMessages: false, sending: false, stage: '', controller: null as AbortController | null, lastError: '',
  }),
  getters: {
    currentKey: (state) => state.currentSessionId || DRAFT_KEY,
    currentMessages(): ChatMessage[] { return this.messages[this.currentKey] || [] },
    subjectLocked(): boolean { return this.currentMessages.some((message) => message.role === 'user') },
    currentSession(): ChatSession | undefined { return this.sessions.find((session) => session.id === this.currentSessionId) },
  },
  actions: {
    async loadSessions() { this.loadingSessions = true; try { this.sessions = await getSessions() } finally { this.loadingSessions = false } },
    async openSession(id: string) {
      this.currentSessionId = id
      const session = this.sessions.find((item) => item.id === id)
      if (session?.subject) this.setSubject(session.subject)
      if (this.messages[id]) return
      this.loadingMessages = true
      try { this.messages[id] = await getSessionMessages(id) } finally { this.loadingMessages = false }
    },
    newSession() { this.stop(); this.currentSessionId = ''; this.messages[DRAFT_KEY] = []; this.lastError = '' },
    setSubject(subject: Subject) { if (this.subjectLocked && subject !== this.subject) return; this.subject = subject; localStorage.setItem('education_subject', subject) },
    async rename(id: string, title: string) { const updated = await renameSession(id, title); const index = this.sessions.findIndex((s) => s.id === id); if (index >= 0) this.sessions[index] = updated },
    async remove(id: string) { await deleteSession(id); delete this.messages[id]; this.sessions = this.sessions.filter((s) => s.id !== id); if (this.currentSessionId === id) this.newSession() },
    stop() {
      this.controller?.abort(); this.controller = null; this.sending = false; this.stage = ''
      const last = this.currentMessages.at(-1); if (last?.streaming) { last.streaming = false; if (!last.content) last.content = '已停止生成。' }
    },
    async send(question: string) {
      const text = question.trim(); if (!text || this.sending) return
      const startingKey = this.currentKey; if (!this.messages[startingKey]) this.messages[startingKey] = []
      const userMessage: ChatMessage = { role: 'user', content: text, created_at: new Date().toISOString() }
      const assistantDraft: ChatMessage = { role: 'assistant', content: '', citations: [], retrieved_chunks: [], confidence: '', route: '', streaming: true }
      this.messages[startingKey].push(userMessage, assistantDraft)
      const assistantMessage = this.messages[startingKey][this.messages[startingKey].length - 1]
      this.sending = true; this.stage = 'routing'; this.lastError = ''; this.controller = new AbortController()
      let backendSessionId = this.currentSessionId; let streamError = ''; const meta = SUBJECT_META[this.subject]
      const payload: ChatRequest = { question: text, subject: this.subject, collection_name: meta.collection, session_id: this.currentSessionId || null }
      try {
        await streamChat(payload, ({ event, data }) => {
          if (event === 'status') { this.stage = String(data.stage || ''); if (data.session_id) backendSessionId = String(data.session_id) }
          else if (event === 'sources') { assistantMessage.route = String(data.route || '') as ChatMessage['route']; assistantMessage.confidence = String(data.confidence || '') as Confidence; assistantMessage.citations = (data.citations || []) as ChatMessage['citations']; assistantMessage.retrieved_chunks = (data.retrieved_chunks || []) as RetrievedChunk[] }
          else if (event === 'delta') assistantMessage.content += String(data.text || '')
          else if (event === 'done') backendSessionId = String(data.session_id || backendSessionId)
          else if (event === 'error') streamError = String(data.detail || '回答生成失败')
        }, this.controller.signal)
        if (streamError) throw new Error(streamError)
        assistantMessage.streaming = false; if (!assistantMessage.content) assistantMessage.content = '暂时没有生成回答。'
        if (backendSessionId && startingKey === DRAFT_KEY) { this.messages[backendSessionId] = this.messages[DRAFT_KEY]; delete this.messages[DRAFT_KEY]; this.currentSessionId = backendSessionId }
        await this.loadSessions()
      } catch (error) {
        assistantMessage.streaming = false
        if (this.controller?.signal.aborted) { if (!assistantMessage.content) assistantMessage.content = '已停止生成。' }
        else { const message = error instanceof Error ? error.message : '请求失败，请稍后重试'; assistantMessage.error = message; assistantMessage.retry_question = text; if (!assistantMessage.content) assistantMessage.content = '本次回答未完成。'; this.lastError = message }
      } finally { this.sending = false; this.stage = ''; this.controller = null }
    },
  },
})
