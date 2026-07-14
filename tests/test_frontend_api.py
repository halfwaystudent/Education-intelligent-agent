from __future__ import annotations

from datetime import datetime

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.api.chat as chat_api
from app.api.chat import router as chat_router
from app.api.collections import router as collections_router
from app.models.db import Base, ChatMessage, ChatSession, Chunk, Course, Document, get_db


def build_client(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    testing_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_db():
        db = testing_session()
        try:
            yield db
        finally:
            db.close()

    app = FastAPI()
    app.include_router(chat_router)
    app.include_router(collections_router)
    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(chat_api, "SessionLocal", testing_session)
    return TestClient(app), testing_session


def test_session_crud_and_complete_message_history(tmp_path, monkeypatch):
    client, session_factory = build_client(tmp_path, monkeypatch)
    db = session_factory()
    db.add(ChatSession(id="session-1", title="导数问题", subject="数学", collection_name="math_collection", created_at=datetime.utcnow(), updated_at=datetime.utcnow()))
    db.add(ChatMessage(session_id="session-1", role="assistant", content="回答", route="concept_explain", confidence="high", citations=[{"chunk_id": "c1"}], retrieved_chunks=[{"content": "资料", "metadata": {"chunk_id": "c1"}}]))
    db.commit()
    db.close()

    sessions = client.get("/api/chat/sessions")
    assert sessions.status_code == 200
    assert sessions.json()[0]["title"] == "导数问题"
    assert sessions.json()[0]["message_count"] == 1

    messages = client.get("/api/chat/session-1/messages")
    assert messages.status_code == 200
    assert messages.json()[0]["confidence"] == "high"
    assert messages.json()[0]["retrieved_chunks"][0]["metadata"]["chunk_id"] == "c1"

    renamed = client.patch("/api/chat/sessions/session-1", json={"title": "新的标题"})
    assert renamed.status_code == 200
    assert renamed.json()["title"] == "新的标题"

    deleted = client.delete("/api/chat/sessions/session-1")
    assert deleted.status_code == 200
    assert client.get("/api/chat/sessions").json() == []


def test_stream_chat_persists_messages(tmp_path, monkeypatch):
    client, session_factory = build_client(tmp_path, monkeypatch)
    monkeypatch.setattr(chat_api, "prepare_question", lambda *args, **kwargs: {
        "question": "什么是导数",
        "route": "concept_explain",
        "chunks": [],
        "citations": [],
        "confidence": "low",
    })
    monkeypatch.setattr(chat_api, "stream_prepared_answer", lambda prepared: iter(["这是", "流式回答"]))

    response = client.post("/api/chat/stream", json={
        "question": "什么是导数",
        "subject": "数学",
        "collection_name": "math_collection",
    })
    assert response.status_code == 200
    assert "event: sources" in response.text
    assert "这是" in response.text
    assert "流式回答" in response.text
    assert "event: done" in response.text

    db = session_factory()
    messages = db.query(ChatMessage).order_by(ChatMessage.id).all()
    assert [item.role for item in messages] == ["user", "assistant"]
    assert messages[1].content == "这是流式回答"
    assert messages[1].confidence == "low"
    db.close()


def test_collection_summary_and_documents(tmp_path, monkeypatch):
    client, session_factory = build_client(tmp_path, monkeypatch)
    db = session_factory()
    course = Course(name="math_collection", description="数学")
    db.add(course); db.commit(); db.refresh(course)
    indexed = Document(course_id=course.id, file_name="math.pdf", source_path="math.pdf", status="indexed")
    failed = Document(course_id=course.id, file_name="bad.pdf", source_path="bad.pdf", status="failed", error_message="OCR 失败")
    db.add_all([indexed, failed]); db.commit(); db.refresh(indexed)
    db.add(Chunk(course_id=course.id, document_id=indexed.id, chunk_id="chunk-1", content="函数与导数", metadata_json={}))
    db.commit(); db.close()

    summaries = client.get("/api/collections").json()
    math = next(item for item in summaries if item["subject"] == "数学")
    assert math["document_count"] == 2
    assert math["chunk_count"] == 1
    assert math["indexed_count"] == 1
    assert math["failed_count"] == 1

    documents = client.get("/api/collections/math_collection/documents").json()
    assert len(documents) == 2
    assert next(item for item in documents if item["file_name"] == "math.pdf")["chunk_count"] == 1
