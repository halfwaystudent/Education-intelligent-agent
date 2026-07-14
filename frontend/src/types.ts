export type Subject = '语文' | '数学' | '英语'
export type Confidence = 'low' | 'medium' | 'high' | ''
export type ChatRoute = 'knowledge_qa' | 'problem_solving' | 'concept_explain' | 'out_of_scope' | ''

export interface Citation { file_name: string; page: number | null; section_title: string; chunk_id: string }
export interface RetrievedChunk {
  content: string
  score?: number
  metadata: Record<string, unknown> & {
    chunk_id?: string; file_name?: string; page?: number | string | null; section_title?: string
    question_no?: string; question_type?: string; display_html?: string; question_image_url?: string
    display_image_urls?: string[]; embedding_text?: string; visual_ocr_text?: string
  }
}
export interface ChatMessage {
  id?: number | string; role: 'user' | 'assistant'; content: string; route?: ChatRoute; confidence?: Confidence
  citations?: Citation[]; retrieved_chunks?: RetrievedChunk[]; created_at?: string; streaming?: boolean; error?: string; retry_question?: string
}
export interface ChatSession {
  id: string; title: string; subject: Subject | ''; collection_name: string; course_id: number | null
  created_at: string; updated_at: string; message_count: number
}
export interface ChatRequest { question: string; course_id?: number | null; session_id?: string | null; subject: Subject; collection_name: string }
export interface CollectionSummary {
  name: string; subject: Subject; course_id: number | null; document_count: number; chunk_count: number
  indexed_count: number; pending_count: number; failed_count: number; updated_at: string | null
}
export interface DocumentRecord { id: number; course_id: number; file_name: string; status: string; error_message: string; created_at: string; chunk_count: number }
export interface ChunkRecord { chunk_id: string; content: string; page: number | null; section_title: string; metadata: RetrievedChunk['metadata'] }
export interface UploadResult {
  document_id: number; file_name: string; status: string; collection: string; subject: Subject; agent: string
  chunks: number; products: string[]; error_message: string
}
export interface PaperQuestion {
  question_no: string; question_type: string; stem: string; options: string[]; answer: string; analysis: string
  knowledge_points: string[]; page: number | null; source_file: string; question_image_url: string
  display_html: string; display_image_urls: string[]; quality_flags: string[]; chunk_id: string
}
export interface PaperAnalysisResult {
  document_id: number; file_name: string; subject: Subject; agent: string; collection: string; chunks: number
  report_markdown: string; questions: PaperQuestion[]; citations: Citation[]; retrieved_chunks: RetrievedChunk[]
  status: string; error_message: string
}
export interface DiagnosticResult { route: ChatRoute; confidence: Confidence; citations: Citation[]; retrieved_chunks: RetrievedChunk[] }
export type StreamEventName = 'status' | 'sources' | 'delta' | 'done' | 'error'
export interface StreamEvent { event: StreamEventName; data: Record<string, unknown> }
