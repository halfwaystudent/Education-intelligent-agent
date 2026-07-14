from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class CourseCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class CourseRead(BaseModel):
    id: int
    name: str
    description: str
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentRead(BaseModel):
    id: int
    course_id: int
    file_name: str
    status: str
    error_message: str = ""
    created_at: datetime

    model_config = {"from_attributes": True}


class ChunkRead(BaseModel):
    chunk_id: str
    content: str
    page: int | None = None
    section_title: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatRequest(BaseModel):
    question: str = Field(min_length=1)
    course_id: int | None = None
    session_id: str | None = None
    subject: str | None = None
    collection_name: str | None = None


class Citation(BaseModel):
    file_name: str
    page: int | None = None
    section_title: str = ""
    chunk_id: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[Citation]
    route: Literal["knowledge_qa", "problem_solving", "concept_explain", "out_of_scope"]
    confidence: Literal["low", "medium", "high"]
    session_id: str
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)


class ChatSessionUpdate(BaseModel):
    title: str = Field(min_length=1, max_length=200)


class ChatSessionRead(BaseModel):
    id: str
    title: str = ""
    subject: str = ""
    collection_name: str = ""
    course_id: int | None = None
    created_at: datetime
    updated_at: datetime
    message_count: int = 0


class ChatMessageRead(BaseModel):
    id: int
    role: str
    content: str
    route: str = ""
    confidence: str = ""
    citations: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    created_at: datetime


class UploadResponse(BaseModel):
    document_id: int
    file_name: str
    status: str
    collection: str
    subject: str = ""
    agent: str
    chunks: int
    products: list[str] = Field(default_factory=list)
    error_message: str = ""


class PaperAnalyzeResponse(BaseModel):
    document_id: int
    file_name: str
    subject: str
    agent: str
    collection: str
    chunks: int
    report_markdown: str
    questions: list[dict[str, Any]] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
    status: str
    error_message: str = ""


class CollectionSummary(BaseModel):
    name: str
    subject: str
    course_id: int | None = None
    document_count: int = 0
    chunk_count: int = 0
    indexed_count: int = 0
    pending_count: int = 0
    failed_count: int = 0
    updated_at: datetime | None = None


class CollectionDocumentRead(DocumentRead):
    chunk_count: int = 0


class RetrievalDiagnosticRequest(BaseModel):
    question: str = Field(min_length=1)


class RetrievalDiagnosticResponse(BaseModel):
    route: str
    confidence: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    retrieved_chunks: list[dict[str, Any]] = Field(default_factory=list)
