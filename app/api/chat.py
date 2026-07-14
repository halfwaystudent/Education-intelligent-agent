import json
from datetime import datetime
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.models.db import ChatMessage, ChatSession, Course, SessionLocal, get_db
from app.models.schemas import (
    ChatRequest,
    ChatResponse,
    ChatSessionRead,
    ChatSessionUpdate,
)
from app.rag.chains import answer_question, prepare_question, stream_prepared_answer
from app.storage.collections import COLLECTION_SUBJECTS, normalize_subject, resolve_collection_name

router = APIRouter(prefix="/api/chat", tags=["chat"])


def _session_title(question: str) -> str:
    value = " ".join(question.strip().split())
    return value if len(value) <= 24 else value[:24].rstrip() + "..."


def _resolve_subject(subject: str | None, collection_name: str) -> str:
    return normalize_subject(subject) or COLLECTION_SUBJECTS.get(collection_name, "")


def _resolve_collection_for_payload(db: Session, payload: ChatRequest) -> str:
    course = db.get(Course, payload.course_id) if payload.course_id is not None else None
    if payload.course_id is not None and course is None:
        raise HTTPException(status_code=404, detail="课程不存在")
    try:
        if payload.subject or payload.collection_name:
            return resolve_collection_name(
                subject=payload.subject,
                collection_name=payload.collection_name,
            )
        if course is not None:
            return resolve_collection_name(collection_name=course.name)
        raise ValueError("请提供 subject、collection_name 或 course_id，不能查询空的默认知识库")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _get_or_create_session(db: Session, payload: ChatRequest, collection_name: str) -> ChatSession:
    session_id = payload.session_id or uuid4().hex
    session = db.get(ChatSession, session_id)
    subject = _resolve_subject(payload.subject, collection_name)
    now = datetime.utcnow()
    if session:
        if session.collection_name and session.collection_name != collection_name:
            raise HTTPException(status_code=409, detail="当前会话已绑定其他学科，请新建会话后再切换学科")
        session.subject = session.subject or subject
        session.collection_name = session.collection_name or collection_name
        session.title = session.title or _session_title(payload.question)
        session.updated_at = now
    else:
        session = ChatSession(
            id=session_id,
            course_id=payload.course_id,
            title=_session_title(payload.question),
            subject=subject,
            collection_name=collection_name,
            created_at=now,
            updated_at=now,
        )
        db.add(session)
    db.flush()
    return session


def _record_user_message(db: Session, session: ChatSession, question: str) -> None:
    db.add(ChatMessage(session_id=session.id, role="user", content=question))
    session.updated_at = datetime.utcnow()
    db.commit()


def _record_assistant_message(session_id: str, result: dict) -> None:
    db = SessionLocal()
    try:
        db.add(
            ChatMessage(
                session_id=session_id,
                role="assistant",
                content=result["answer"],
                route=result["route"],
                confidence=result["confidence"],
                citations=result["citations"],
                retrieved_chunks=result["retrieved_chunks"],
            )
        )
        session = db.get(ChatSession, session_id)
        if session:
            session.updated_at = datetime.utcnow()
        db.commit()
    finally:
        db.close()


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


@router.get("/sessions", response_model=list[ChatSessionRead])
def list_sessions(db: Session = Depends(get_db)):
    sessions = db.query(ChatSession).order_by(ChatSession.updated_at.desc(), ChatSession.created_at.desc()).all()
    result = []
    for session in sessions:
        count = db.query(ChatMessage).filter(ChatMessage.session_id == session.id).count()
        result.append(
            ChatSessionRead(
                id=session.id,
                title=session.title or "新对话",
                subject=session.subject or "",
                collection_name=session.collection_name or "",
                course_id=session.course_id,
                created_at=session.created_at,
                updated_at=session.updated_at or session.created_at,
                message_count=count,
            )
        )
    return result


@router.patch("/sessions/{session_id}", response_model=ChatSessionRead)
def update_session(session_id: str, payload: ChatSessionUpdate, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    session.title = payload.title.strip()
    session.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(session)
    count = db.query(ChatMessage).filter(ChatMessage.session_id == session.id).count()
    return ChatSessionRead(
        id=session.id,
        title=session.title,
        subject=session.subject or "",
        collection_name=session.collection_name or "",
        course_id=session.course_id,
        created_at=session.created_at,
        updated_at=session.updated_at or session.created_at,
        message_count=count,
    )


@router.delete("/sessions/{session_id}")
def delete_session(session_id: str, db: Session = Depends(get_db)):
    session = db.get(ChatSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")
    db.query(ChatMessage).filter(ChatMessage.session_id == session_id).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return {"deleted": True, "session_id": session_id}


@router.post("/stream")
def chat_stream(payload: ChatRequest, db: Session = Depends(get_db)):
    collection_name = _resolve_collection_for_payload(db, payload)

    session = _get_or_create_session(db, payload, collection_name)
    session_id = session.id
    _record_user_message(db, session, payload.question)

    def event_stream():
        try:
            yield _sse("status", {"stage": "routing", "session_id": session_id})
            yield _sse("status", {"stage": "retrieving"})
            prepared = prepare_question(
                payload.question,
                course_id=payload.course_id,
                collection_name=collection_name,
            )
            yield _sse(
                "sources",
                {
                    "route": prepared["route"],
                    "confidence": prepared["confidence"],
                    "citations": prepared["citations"],
                    "retrieved_chunks": prepared["chunks"],
                },
            )
            yield _sse("status", {"stage": "generating"})
            answer_parts = []
            for delta in stream_prepared_answer(prepared):
                answer_parts.append(delta)
                yield _sse("delta", {"text": delta})
            result = {
                "answer": "".join(answer_parts),
                "route": prepared["route"],
                "confidence": prepared["confidence"],
                "citations": prepared["citations"],
                "retrieved_chunks": prepared["chunks"],
            }
            _record_assistant_message(session_id, result)
            yield _sse("done", {"session_id": session_id, "completed": True})
        except GeneratorExit:
            return
        except Exception as exc:
            yield _sse("error", {"detail": f"回答生成失败：{exc}"})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("", response_model=ChatResponse)
def chat(payload: ChatRequest, db: Session = Depends(get_db)):
    collection_name = _resolve_collection_for_payload(db, payload)

    session = _get_or_create_session(db, payload, collection_name)
    _record_user_message(db, session, payload.question)
    result = answer_question(payload.question, payload.course_id, collection_name=collection_name)
    db.add(
        ChatMessage(
            session_id=session.id,
            role="assistant",
            content=result["answer"],
            route=result["route"],
            confidence=result["confidence"],
            citations=result["citations"],
            retrieved_chunks=result["retrieved_chunks"],
        )
    )
    session.updated_at = datetime.utcnow()
    db.commit()
    return ChatResponse(
        answer=result["answer"],
        citations=result["citations"],
        route=result["route"],
        confidence=result["confidence"],
        session_id=session.id,
        retrieved_chunks=result["retrieved_chunks"],
    )


@router.get("/{session_id}/messages")
def list_messages(session_id: str, db: Session = Depends(get_db)):
    if not db.get(ChatSession, session_id):
        raise HTTPException(status_code=404, detail="会话不存在")
    messages = db.query(ChatMessage).filter(ChatMessage.session_id == session_id).order_by(ChatMessage.id.asc()).all()
    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "route": message.route or "",
            "confidence": message.confidence or "",
            "citations": message.citations or [],
            "retrieved_chunks": message.retrieved_chunks or [],
            "created_at": message.created_at,
        }
        for message in messages
    ]
