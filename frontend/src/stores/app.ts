import { defineStore } from 'pinia'
import type { RetrievedChunk } from '../types'

type ThemeMode = 'light' | 'dark' | 'system'

export const useAppStore = defineStore('app', {
  state: () => ({
    theme: (localStorage.getItem('education_theme') as ThemeMode) || 'system',
    sidebarOpen: false,
    sourceOpen: false,
    selectedChunk: null as RetrievedChunk | null,
  }),
  actions: {
    applyTheme() {
      const dark = this.theme === 'dark' || (this.theme === 'system' && matchMedia('(prefers-color-scheme: dark)').matches)
      document.documentElement.dataset.theme = dark ? 'dark' : 'light'
      document.documentElement.classList.toggle('dark', dark)
    },
    setTheme(theme: ThemeMode) {
      this.theme = theme
      localStorage.setItem('education_theme', theme)
      this.applyTheme()
    },
    openSource(chunk: RetrievedChunk) {
      this.selectedChunk = chunk
      this.sourceOpen = true
    },
  },
})
