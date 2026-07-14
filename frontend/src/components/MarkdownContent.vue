<script setup lang="ts">
import { computed } from 'vue'
import { renderMarkdown } from '../utils/render'

const props = defineProps<{ content: string }>()
const html = computed(() => renderMarkdown(props.content))
</script>

<template><div class="markdown-body" v-html="html" /></template>
