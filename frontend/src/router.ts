import { createRouter, createWebHistory } from 'vue-router'

export default createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', redirect: '/chat' },
    { path: '/chat/:sessionId?', name: 'chat', component: () => import('./views/ChatView.vue') },
    { path: '/papers', name: 'papers', component: () => import('./views/PapersView.vue') },
    { path: '/knowledge', name: 'knowledge', component: () => import('./views/KnowledgeView.vue') },
    { path: '/:pathMatch(.*)*', redirect: '/chat' },
  ],
})
