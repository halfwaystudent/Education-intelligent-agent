from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.models.db import Chunk, Course, Document, get_db
from app.models.schemas import (
    CollectionDocumentRead,
    CollectionSummary,
    RetrievalDiagnosticRequest,
    RetrievalDiagnosticResponse,
)
from app.rag.chains import prepare_question
from app.storage.collections import COLLECTION_SUBJECTS, normalize_collection_name

router = APIRouter(prefix="/api/collections", tags=["collections"])


@router.get("", response_model=list[CollectionSummary])
def list_collections(db: Session = Depends(get_db)):
    result = []
    for collection_name, subject in COLLECTION_SUBJECTS.items():
        course = db.query(Course).filter(Course.name == collection_name).first()
        documents = [] if course is None else db.query(Document).filter(Document.course_id == course.id).all()
        document_ids = [item.id for item in documents]
        chunk_count = 0
        if document_ids:
            chunk_count = db.query(Chunk).filter(Chunk.document_id.in_(document_ids)).count()
        updated_candidates = [item.created_at for item in documents]
        if course:
            updated_candidates.append(course.created_at)
        result.append(
            CollectionSummary(
                name=collection_name,
                subject=subject,
                course_id=course.id if course else None,
                document_count=len(documents),
                chunk_count=chunk_count,
                indexed_count=sum(item.status == "indexed" for item in documents),
                pending_count=sum(item.status == "pending" for item in documents),
                failed_count=sum(item.status == "failed" for item in documents),
                updated_at=max(updated_candidates) if updated_candidates else None,
            )
        )
    return result


@router.get("/{collection_name}/documents", response_model=list[CollectionDocumentRead])
def list_collection_documents(collection_name: str, db: Session = Depends(get_db)):
    try:
        normalized = normalize_collection_name(collection_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    course = db.query(Course).filter(Course.name == normalized).first()
    if not course:
        return []
    documents = db.query(Document).filter(Document.course_id == course.id).order_by(Document.created_at.desc()).all()
    return [
        CollectionDocumentRead(
            id=document.id,
            course_id=document.course_id,
            file_name=document.file_name,
            status=document.status,
            error_message=document.error_message or "",
            created_at=document.created_at,
            chunk_count=db.query(Chunk).filter(Chunk.document_id == document.id).count(),
        )
        for document in documents
    ]


@router.post("/{collection_name}/search", response_model=RetrievalDiagnosticResponse)
def diagnose_collection(
    collection_name: str,
    payload: RetrievalDiagnosticRequest,
):
    try:
        normalized = normalize_collection_name(collection_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    prepared = prepare_question(payload.question, collection_name=normalized)
    return RetrievalDiagnosticResponse(
        route=prepared["route"],
        confidence=prepared["confidence"],
        citations=prepared["citations"],
        retrieved_chunks=prepared["chunks"],
    )
