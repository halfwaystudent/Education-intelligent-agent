import { describe, expect, it } from 'vitest'
import { SUBJECT_META } from '../constants'
import { renderMarkdown, sanitizeQuestionHtml } from './render'

describe('subject mapping', () => {
  it('maps the three subjects to fixed collections', () => {
    expect(SUBJECT_META.语文.collection).toBe('chinese_collection')
    expect(SUBJECT_META.数学.collection).toBe('math_collection')
    expect(SUBJECT_META.英语.collection).toBe('english_collection')
  })
})

describe('safe rendering', () => {
  it('renders markdown and KaTeX', () => {
    const html = renderMarkdown('公式：$x^2$')
    expect(html).toContain('katex')
    expect(html).toContain('公式')
  })

  it('removes scripts, event handlers and external images', () => {
    const html = sanitizeQuestionHtml('<script>alert(1)</script><img src="https://evil.example/a.png" onerror="alert(1)"><img src="/media/questions/a.png">')
    expect(html).not.toContain('<script')
    expect(html).not.toContain('onerror')
    expect(html).not.toContain('evil.example')
    expect(html).toContain('/media/questions/a.png')
  })
})
