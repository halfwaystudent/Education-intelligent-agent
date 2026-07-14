import type {
  ChatMessage,
  ChatRequest,
  ChatSession,
  ChunkRecord,
  CollectionSummary,
  DiagnosticResult,
  DocumentRecord,
  PaperAnalysisResult,
  StreamEvent,
  UploadResult,
} from './types'

const API_BASE = String(import.meta.env.VITE_API_BASE_URL || '').replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  detail: string

  constructor(message: string, status = 0, detail = '') {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

async function responseError(response: Response): Promise<ApiError> {
  const raw = await response.text()
  let detail = raw
  try {
    const parsed = JSON.parse(raw)
    detail = parsed.detail || parsed.message || raw
  } catch {
    // Keep the raw response for non-JSON failures.
  }
  const friendly = response.status === 413 ? '文件不能超过 50MB' : detail || `请求失败（${response.status}）`
  return new ApiError(friendly, response.status, raw)
}

export async function apiFetch<T>(path: string, init: RequestInit = {}, timeoutMs = 30_000): Promise<T> {
  const controller = new AbortController()
  const timer = window.setTimeout(() => controller.abort('timeout'), timeoutMs)
  const externalSignal = init.signal
  if (externalSignal) externalSignal.addEventListener('abort', () => controller.abort(), { once: true })
  try {
    const response = await fetch(`${API_BASE}${path}`, { ...init, signal: controller.signal })
    if (!response.ok) throw await responseError(response)
    if (response.status === 204) return undefined as T
    return await response.json() as T
  } catch (error) {
    if (error instanceof ApiError) throw error
    if (controller.signal.aborted) throw new ApiError('请求已中断或超时，请稍后重试')
    throw new ApiError(error instanceof Error ? error.message : '无法连接后端服务')
  } finally {
    window.clearTimeout(timer)
  }
}

export const getSessions = () => apiFetch<ChatSession[]>('/api/chat/sessions')
export const getSessionMessages = (id: string) => apiFetch<ChatMessage[]>(`/api/chat/${encodeURIComponent(id)}/messages`)
export const renameSession = (id: string, title: string) => apiFetch<ChatSession>(`/api/chat/sessions/${encodeURIComponent(id)}`, {
  method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ title }),
})
export const deleteSession = (id: string) => apiFetch<{ deleted: boolean }>(`/api/chat/sessions/${encodeURIComponent(id)}`, { method: 'DELETE' })
export const getCollections = () => apiFetch<CollectionSummary[]>('/api/collections')
export const getCollectionDocuments = (name: string) => apiFetch<DocumentRecord[]>(`/api/collections/${encodeURIComponent(name)}/documents`)
export const getDocumentChunks = (id: number) => apiFetch<ChunkRecord[]>(`/api/documents/${id}/chunks`)
export const reindexCourse = (courseId: number) => apiFetch<Record<string, number>>(`/api/courses/${courseId}/reindex`, { method: 'POST' }, 15 * 60_000)

export async function streamChat(
  payload: ChatRequest,
  onEvent: (event: StreamEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}/api/chat/stream`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
    body: JSON.stringify(payload),
    signal,
  })
  if (!response.ok) throw await responseError(response)
  if (!response.body) throw new ApiError('浏览器未收到流式响应')

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { done, value } = await reader.read()
    buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
    const blocks = buffer.split(/\r?\n\r?\n/)
    buffer = blocks.pop() || ''
    for (const block of blocks) {
      let event = 'message'
      const dataLines: string[] = []
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith('event:')) event = line.slice(6).trim()
        if (line.startsWith('data:')) dataLines.push(line.slice(5).trim())
      }
      if (!dataLines.length) continue
      const data = JSON.parse(dataLines.join('\n')) as Record<string, unknown>
      onEvent({ event: event as StreamEvent['event'], data })
    }
    if (done) break
  }
}

function uploadForm(file: File, fields: Record<string, string>): FormData {
  const form = new FormData()
  form.append('file', file)
  Object.entries(fields).forEach(([key, value]) => form.append(key, value))
  return form
}

export const uploadKnowledge = (subject: string, collection: string, file: File) => apiFetch<UploadResult>('/api/upload', {
  method: 'POST', body: uploadForm(file, { subject, collection_name: collection }),
}, 15 * 60_000)

export const analyzePaper = (subject: string, question: string, file: File) => apiFetch<PaperAnalysisResult>('/api/papers/analyze', {
  method: 'POST', body: uploadForm(file, { subject, question }),
}, 15 * 60_000)

export const diagnoseRetrieval = (collection: string, question: string) => apiFetch<DiagnosticResult>(`/api/collections/${encodeURIComponent(collection)}/search`, {
  method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ question }),
}, 5 * 60_000)
