import DOMPurify from 'dompurify'
import MarkdownIt from 'markdown-it'
import markdownItKatex from 'markdown-it-katex'
const markdown = new MarkdownIt({ html: false, linkify: true, breaks: true, typographer: true }).use(markdownItKatex)
const ALLOWED_MEDIA_PREFIXES = ['/media/formulas/', '/media/questions/']
function restrictMedia(html: string): string {
  const template = document.createElement('template'); template.innerHTML = html
  template.content.querySelectorAll('img').forEach((image) => {
    const src = image.getAttribute('src') || ''
    if (!ALLOWED_MEDIA_PREFIXES.some((prefix) => src.startsWith(prefix))) { image.remove(); return }
    image.setAttribute('loading', 'lazy'); image.removeAttribute('srcset')
  })
  template.content.querySelectorAll('a').forEach((anchor) => { anchor.setAttribute('target', '_blank'); anchor.setAttribute('rel', 'noopener noreferrer') })
  return template.innerHTML
}
export function renderMarkdown(value: string): string {
  const clean = DOMPurify.sanitize(markdown.render(String(value || '')), { USE_PROFILES: { html: true }, ADD_TAGS: ['math', 'semantics', 'annotation'], ADD_ATTR: ['aria-hidden'] })
  return restrictMedia(clean)
}
export function sanitizeQuestionHtml(value: string): string {
  const clean = DOMPurify.sanitize(String(value || ''), { ALLOWED_TAGS: ['section', 'div', 'h4', 'p', 'span', 'br', 'img', 'ol', 'ul', 'li', 'strong', 'em'], ALLOWED_ATTR: ['class', 'src', 'alt', 'loading'] })
  return restrictMedia(clean)
}
export function cleanDisplayText(value: string): string {
  return String(value || '').replace(/\b\d+\.(?:jpeg|jpg|png|gif|webp)\]\[IMAGE_\d+:[^\]]*(?:\]|$)/gi, '[图片/公式]').replace(/\[IMAGE_\d+(?::[^\]]*)?(?:\]|$)/g, '[图片/公式]').replace(/\[FORMULA:([^\]]+)\]/g, '$1').replace(/\b(?:rld|rid)\d*\b/gi, '').replace(/(题型：\S+\s+题号：\S+)\s+\1/g, '$1').replace(/\s+/g, ' ').trim()
}
