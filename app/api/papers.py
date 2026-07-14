from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.agents.paper_analyzer import analyze_indexed_paper, validate_paper_file_name
from app.agents.subject_agents import get_subject_agent
from app.models.db import Course, Document, get_db
from app.models.schemas import PaperAnalyzeResponse
from app.storage.collections import normalize_subject, resolve_collection_name
from app.storage.filestore import save_collection_upload_file

router = APIRouter(prefix="/api/papers", tags=["papers"])
ALLOWED_SUBJECTS = {"语文", "数学", "英语"}


@router.post("/analyze", response_model=PaperAnalyzeResponse)
async def analyze_paper(
    file: UploadFile = File(...),
    subject: str = Form(...),
    question: str = Form(""),
    db: Session = Depends(get_db),
):
    try:
        validate_paper_file_name(file.filename or "")
        normalized_subject = normalize_subject(subject)
        if normalized_subject not in ALLOWED_SUBJECTS:
            raise ValueError("subject 仅支持 语文、数学、英语")
        collection_name = resolve_collection_name(subject=normalized_subject)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    agent = get_subject_agent(subject=normalized_subject, collection_name=collection_name)
    dataset = db.query(Course).filter(Course.name == collection_name).first()
    if not dataset:
        dataset = Course(name=collection_name, description=f"{normalized_subject} paper knowledge collection")
        db.add(dataset)
        db.commit()
        db.refresh(dataset)

    path = await save_collection_upload_file(file, collection_name)
    document = Document(
        course_id=dataset.id,
        file_name=file.filename or path.name,
        source_path=str(path),
        status="pending",
    )
    db.add(document)
    db.commit()
    db.refresh(document)

    try:
        ingest_result = agent.ingest(db, document, collection_name=collection_name, subject=normalized_subject)
        db.refresh(document)
        analysis = analyze_indexed_paper(
            db=db,
            document=document,
            agent=agent,
            collection_name=collection_name,
            question=question,
        )
    except Exception as exc:
        db.refresh(document)
        raise HTTPException(status_code=500, detail=f"试卷解析失败：{exc}") from exc

    return PaperAnalyzeResponse(
        document_id=document.id,
        file_name=document.file_name,
        subject=normalized_subject,
        agent=agent.name,
        collection=ingest_result.get("collection", collection_name),
        chunks=ingest_result.get("chunks", 0),
        report_markdown=analysis["report_markdown"],
        questions=analysis["questions"],
        citations=analysis["citations"],
        retrieved_chunks=analysis["retrieved_chunks"],
        status=document.status,
        error_message=document.error_message or "",
    )
