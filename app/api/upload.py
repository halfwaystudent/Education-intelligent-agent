from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agents.subject_agents import get_subject_agent
from app.models.db import Course, Document, get_db
from app.models.schemas import UploadResponse
from app.storage.collections import resolve_collection_name
from app.storage.filestore import save_collection_upload_file

router = APIRouter(tags=["upload"])


@router.post("/api/upload", response_model=UploadResponse)
async def upload_file(
    file: UploadFile = File(...),
    subject: str = Form(""),
    collection_name: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        target_collection = resolve_collection_name(subject=subject, collection_name=collection_name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    dataset = db.query(Course).filter(Course.name == target_collection).first()
    if not dataset:
        dataset = Course(name=target_collection, description=f"{subject or target_collection} knowledge collection")
        db.add(dataset)
        db.commit()
        db.refresh(dataset)

    path = await save_collection_upload_file(file, target_collection)
    document = Document(
        course_id=dataset.id,
        file_name=file.filename or path.name,
        source_path=str(path),
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    agent = get_subject_agent(subject=subject, collection_name=target_collection)
    result = agent.ingest(db, document, collection_name=target_collection, subject=subject)
    db.refresh(document)
    return UploadResponse(
        document_id=document.id,
        file_name=document.file_name,
        status=document.status,
        collection=result.get("collection", target_collection),
        subject=subject,
        agent=result.get("agent", agent.name),
        chunks=result.get("chunks", 0),
        products=result.get("products", []),
        error_message=document.error_message or "",
    )
