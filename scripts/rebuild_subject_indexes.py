from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agents.subject_agents import get_subject_agent
from app.models.db import Chunk, Course, Document, SessionLocal, init_db
from app.storage.collections import COLLECTION_SUBJECTS
from app.storage.filestore import resolve_document_file

COLLECTIONS = {
    "语文": "chinese_collection",
    "数学": "math_collection",
    "英语": "english_collection",
}


def main() -> None:
    parser = argparse.ArgumentParser(description="重建语文、数学、英语 Chroma 索引")
    parser.add_argument("--subjects", nargs="*", default=list(COLLECTIONS), choices=list(COLLECTIONS))
    parser.add_argument("--limit", type=int, default=0, help="每科最多处理 N 个文档，0 表示全部")
    parser.add_argument("--reset-sqlite", action="store_true", help="先清除所选学科的旧 chunk 元数据")
    parser.add_argument("--force", action="store_true", help="连同已经 indexed 的文档一起重建")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    failures: list[tuple[int, str, str]] = []
    try:
        selected = [(subject, COLLECTIONS[subject]) for subject in args.subjects]
        course_ids = [
            course.id
            for _, collection in selected
            if (course := db.query(Course).filter(Course.name == collection).first()) is not None
        ]
        if args.reset_sqlite and course_ids:
            db.query(Chunk).filter(Chunk.course_id.in_(course_ids)).delete(synchronize_session=False)
            db.query(Document).filter(Document.course_id.in_(course_ids)).update(
                {Document.status: "pending", Document.error_message: ""},
                synchronize_session=False,
            )
            db.commit()

        for subject, collection in selected:
            course = db.query(Course).filter(Course.name == collection).first()
            if course is None:
                print(f"skip {subject}: course {collection} does not exist")
                continue
            query = db.query(Document).filter(Document.course_id == course.id)
            if not args.force:
                query = query.filter(Document.status != "indexed")
            documents = query.order_by(Document.id).all()
            if args.limit > 0:
                documents = documents[: args.limit]
            agent = get_subject_agent(subject=subject, collection_name=collection)
            print(f"[{subject}] documents={len(documents)} collection={collection}")
            for index, document in enumerate(documents, start=1):
                try:
                    resolved = resolve_document_file(document.source_path, document.file_name)
                    document.source_path = str(resolved)
                    document.status = "pending"
                    document.error_message = ""
                    db.commit()
                    result = agent.ingest(db, document, collection_name=collection, subject=subject)
                    print(f"  {index}/{len(documents)} indexed id={document.id} chunks={result['chunks']} {document.file_name}")
                except Exception as exc:
                    db.rollback()
                    failures.append((document.id, document.file_name, str(exc)))
                    print(f"  {index}/{len(documents)} FAILED id={document.id} {document.file_name}: {exc}")

        if failures:
            print("\nfailures:")
            for document_id, file_name, error in failures:
                print(f"- id={document_id} {file_name}: {error}")
            raise SystemExit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
