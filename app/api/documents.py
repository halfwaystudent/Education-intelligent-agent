from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.models.db import Chunk, Course, Document, get_db
from app.models.schemas import ChunkRead, DocumentRead
from app.rag.ingest import ingest_document
from app.storage.filestore import save_upload_file

router = APIRouter(tags=["documents"])


@router.post("/api/courses/{course_id}/documents", response_model=DocumentRead)
async def upload_document(course_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    path = await save_upload_file(course_id, file)
    document = Document(
        course_id=course_id,
        file_name=file.filename or path.name,
        source_path=str(path),
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)
    try:
        ingest_document(db, document)
        db.refresh(document)
    except Exception:
        db.refresh(document)
    return document


@router.post("/api/courses/{course_id}/reindex")
def reindex_course(course_id: int, db: Session = Depends(get_db)):
    course = db.get(Course, course_id)
    if not course:
        raise HTTPException(status_code=404, detail="课程不存在")
    documents = db.query(Document).filter(Document.course_id == course_id).all()
    indexed = 0
    failed = 0
    for document in documents:
        try:
            indexed += ingest_document(db, document)
        except Exception:
            failed += 1
    return {"course_id": course_id, "documents": len(documents), "indexed_chunks": indexed, "failed_documents": failed}


@router.get("/api/documents/{document_id}/chunks", response_model=list[ChunkRead])
def list_document_chunks(document_id: int, db: Session = Depends(get_db)):
    document = db.get(Document, document_id)
    if not document:
        raise HTTPException(status_code=404, detail="文档不存在")
    chunks = db.query(Chunk).filter(Chunk.document_id == document_id).order_by(Chunk.id.asc()).all()
    return [
        ChunkRead(
            chunk_id=chunk.chunk_id,
            content=chunk.content,
            page=chunk.page,
            section_title=chunk.section_title,
            metadata=chunk.metadata_json or {},
        )
        for chunk in chunks
    ]
