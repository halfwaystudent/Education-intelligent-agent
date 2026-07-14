from pathlib import Path
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models.db import Chunk, Document


def clear_document_index(db: Session, document: Document, collection_name: str | None = None) -> None:
    old_chunks = db.query(Chunk).filter(Chunk.document_id == document.id).all()
    old_ids = [chunk.chunk_id for chunk in old_chunks]
    if old_ids:
        from app.storage.vectorstore import get_chroma_collection

        collection = get_chroma_collection(collection_name)
        collection.delete(ids=old_ids)
    db.query(Chunk).filter(Chunk.document_id == document.id).delete()
    db.flush()


def ingest_document(db: Session, document: Document) -> int:
    from app.rag.loaders import load_text_pages
    from app.rag.splitter import split_documents
    from app.storage.vectorstore import get_chroma_collection
    from app.storage.filestore import resolve_document_file

    path = resolve_document_file(document.source_path, document.file_name)
    document.source_path = str(path)
    try:
        clear_document_index(db, document)
        pages = load_text_pages(path)
        chunks = split_documents(pages)
        if not chunks:
            raise ValueError("文档未解析出有效文本")

        collection = get_chroma_collection()
        ids: list[str] = []
        texts: list[str] = []
        metadatas: list[dict] = []
        db_chunks: list[Chunk] = []

        for index, item in enumerate(chunks, start=1):
            chunk_id = f"doc-{document.id}-{index}-{uuid4().hex[:8]}"
            metadata = {
                "course_id": document.course_id,
                "document_id": document.id,
                "file_name": document.file_name,
                "page": item.get("page"),
                "section_title": item.get("section_title", ""),
                "question_no": item.get("question_no", ""),
                "question_type": item.get("question_type", ""),
                "chunk_type": item.get("chunk_type", ""),
                "quality_flags": ";".join(item.get("quality_flags") or []),
                "image_paths": ";".join(item.get("image_paths") or []),
                "display_image_paths": ";".join(item.get("display_image_paths") or []),
                "display_image_urls": ";".join(item.get("display_image_urls") or []),
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
            metadatas.append({k: ("" if v is None else v) for k, v in metadata.items()})
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
        return len(db_chunks)
    except Exception as exc:
        document.status = "failed"
        document.error_message = str(exc)
        db.commit()
        raise
