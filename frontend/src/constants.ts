import type { Confidence, Subject } from './types'

export const SUBJECTS: Subject[] = ['语文', '数学', '英语']
export const SUBJECT_META: Record<Subject, { collection: string; short: string; description: string; color: string; suggestions: string[] }> = {
  '语文': { collection: 'chinese_collection', short: '文', description: '阅读理解、文言文、诗歌鉴赏与写作表达', color: '#db2777', suggestions: ['请分析这篇文章的主旨与结构', '解释这个文言词语在句中的含义', '根据材料给出作文立意和提纲'] },
  '数学': { collection: 'math_collection', short: '数', description: '概念讲解、题目分析、证明与公式推导', color: '#2563eb', suggestions: ['请讲解这道题涉及的知识点', '帮我分步骤分析这道数学题', '检查我的解题思路可能错在哪里'] },
  '英语': { collection: 'english_collection', short: '英', description: '阅读、语法、词汇、翻译与写作修改', color: '#059669', suggestions: ['解释这个句子的语法结构', '分析阅读题答案在原文中的依据', '帮我修改这段英语作文并说明原因'] },
}
export const ROUTE_LABELS: Record<string, string> = { knowledge_qa: '知识问答', problem_solving: '题目解析', concept_explain: '概念解释', out_of_scope: '超出范围' }
export const CONFIDENCE_META: Record<Confidence, { label: string; description: string; type: 'success' | 'warning' | 'info' }> = {
  high: { label: '资料匹配度高', description: '多个资料片段提供了较强支撑', type: 'success' },
  medium: { label: '建议核对资料', description: '已找到相关资料，建议结合引用核对', type: 'warning' },
  low: { label: '资料支撑不足', description: '当前知识库缺少足够匹配内容', type: 'warning' },
  '': { label: '分析中', description: '正在判断资料支撑程度', type: 'info' },
}
export const STATUS_LABELS: Record<string, string> = { indexed: '已完成', pending: '处理中', failed: '失败' }
