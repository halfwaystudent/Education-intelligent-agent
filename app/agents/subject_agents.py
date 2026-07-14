from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.db import Chunk, Document
from app.storage.collections import COLLECTION_SUBJECTS, resolve_collection_name


@dataclass(frozen=True)
class SubjectAgentConfig:
    name: str
    subject: str
    collection_name: str
    report_focus: str


class BaseSubjectAgent:
    def __init__(self, config: SubjectAgentConfig):
        self.config = config
        self.name = config.name
        self.subject = config.subject
        self.collection_name = config.collection_name
        self.report_focus = config.report_focus

    def ingest(self, db: Session, document: Document, collection_name: str | None = None, subject: str = "") -> dict:
        from app.rag.ingest import clear_document_index
        from app.rag.loaders import load_text_pages
        from app.rag.splitter import split_documents
        from app.storage.vectorstore import get_chroma_collection
        from app.storage.filestore import resolve_document_file

        target_collection = collection_name or self.collection_name
        effective_subject = subject.strip() or self.subject
        try:
            source_path = resolve_document_file(document.source_path, document.file_name)
            document.source_path = str(source_path)
            clear_document_index(db, document, target_collection)
            pages = load_text_pages(source_path)
            chunks = split_documents(pages, subject=effective_subject)
            if not chunks:
                raise ValueError("文档未解析出有效文本")

            collection = get_chroma_collection(target_collection)
            ids: list[str] = []
            texts: list[str] = []
            metadatas: list[dict] = []
            db_chunks: list[Chunk] = []

            for index, item in enumerate(chunks, start=1):
                chunk_id = f"doc-{target_collection}-{document.id}-{index}-{uuid4().hex[:8]}"
                metadata = {
                    "collection_name": target_collection,
                    "dataset": target_collection,
                    "subject": effective_subject,
                    "agent": self.name,
                    "course_id": document.course_id,
                    "document_id": document.id,
                    "file_name": document.file_name,
                    "page": item.get("page"),
                    "section_title": item.get("section_title", ""),
                    "question_no": item.get("question_no", ""),
                    "question_type": item.get("question_type", ""),
                    "chunk_type": item.get("chunk_type", ""),
                    "stem": item.get("stem", ""),
                    "options": item.get("options") or [],
                    "answer": item.get("answer", ""),
                    "analysis": item.get("analysis", ""),
                    "comment": item.get("comment", ""),
                    "quality_flags": item.get("quality_flags") or [],
                    "image_paths": item.get("image_paths") or [],
                    "display_image_paths": item.get("display_image_paths") or [],
                    "display_image_urls": item.get("display_image_urls") or [],
                    "question_image_path": item.get("question_image_path", ""),
                    "question_image_url": item.get("question_image_url", ""),
                    "visual_ocr_text": item.get("visual_ocr_text", ""),
                    "display_html": item.get("display_html", ""),
                    "material_id": item.get("material_id", ""),
                    "match_method": item.get("match_method", ""),
                    "match_confidence": item.get("match_confidence", 0.0),
                    "score_rule": item.get("score_rule", ""),
                    "has_material": item.get("has_material", False),
                    "is_composition": item.get("is_composition", False),
                    "layout_type": item.get("layout_type", ""),
                    "chunk_id": chunk_id,
                    "source_path": document.source_path,
                }
                ids.append(chunk_id)
                texts.append(item.get("embedding_text") or item["content"])
                metadatas.append(_metadata_for_chroma(metadata))
                db_chunks.append(
                    Chunk(
                        course_id=document.course_id,
                        document_id=document.id,
                        chunk_id=chunk_id,
                        content=item["content"],
                        page=item.get("page"),
                        section_title=item.get("section_title", ""),
                        metadata_json=metadata,
                    )
                )

            collection.add(ids=ids, documents=texts, metadatas=metadatas)
            db.add_all(db_chunks)
            document.status = "indexed"
            document.error_message = ""
            db.commit()
            return {
                "agent": self.name,
                "collection": target_collection,
                "document_id": document.id,
                "file_name": document.file_name,
                "chunks": len(db_chunks),
            }
        except Exception as exc:
            document.status = "failed"
            document.error_message = str(exc)
            db.commit()
            raise


def _metadata_for_chroma(metadata: dict) -> dict:
    result = {}
    for key, value in metadata.items():
        if value is None:
            result[key] = ""
        elif isinstance(value, list):
            result[key] = ";".join(str(item) for item in value)
        else:
            result[key] = value
    return result


math_agent = BaseSubjectAgent(
    SubjectAgentConfig(
        name="math_agent",
        subject="数学",
        collection_name="math_collection",
        report_focus="突出公式条件、题型分类、解题步骤、证明逻辑和常见计算错误。",
    )
)
chinese_agent = BaseSubjectAgent(
    SubjectAgentConfig(
        name="chinese_agent",
        subject="语文",
        collection_name="chinese_collection",
        report_focus="突出文本理解、文言文、古诗文赏析、语言文字运用和作文立意。",
    )
)
english_agent = BaseSubjectAgent(
    SubjectAgentConfig(
        name="english_agent",
        subject="英语",
        collection_name="english_collection",
        report_focus="突出阅读理解、完形填空、语法结构、翻译表达和写作建议。",
    )
)

SUBJECT_AGENTS = {
    "math_collection": math_agent,
    "chinese_collection": chinese_agent,
    "english_collection": english_agent,
}


def get_subject_agent(subject: str | None = None, collection_name: str | None = None) -> BaseSubjectAgent:
    resolved_collection = resolve_collection_name(subject=subject, collection_name=collection_name)
    return SUBJECT_AGENTS.get(
        resolved_collection,
        BaseSubjectAgent(
            SubjectAgentConfig(
                name="document_agent",
                subject=subject or COLLECTION_SUBJECTS.get(resolved_collection, ""),
                collection_name=resolved_collection,
                report_focus="基于资料生成可追溯的教学式分析。",
            )
        ),
    )
