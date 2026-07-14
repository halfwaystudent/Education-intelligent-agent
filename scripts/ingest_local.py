import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.agents.subject_agents import get_subject_agent
from app.models.db import Course, Document, SessionLocal, init_db
from app.rag.ingest import ingest_document
from app.storage.collections import normalize_subject, resolve_collection_name


SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def iter_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root]
    return sorted(
        path
        for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES and not path.name.startswith("~$")
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="导入本地课程或学科资料到知识库")
    parser.add_argument("--course", default="", help="课程名称；未传 subject/collection-name 时使用旧课程导入流程")
    parser.add_argument("--subject", default="", help="学科名称，例如 语文/数学/英语")
    parser.add_argument("--collection-name", default="", help="显式指定 Chroma collection")
    parser.add_argument("--path", required=True, help="文件或目录路径")
    parser.add_argument("--limit", type=int, default=0, help="只导入前 N 个文件，用于 smoke test")
    parser.add_argument("--force", action="store_true", help="同一 source_path 已有记录时仍然重新创建并导入")
    args = parser.parse_args()

    init_db()
    db = SessionLocal()
    failures: list[tuple[Path, str]] = []
    try:
        files = iter_files(Path(args.path))
        if args.limit > 0:
            files = files[: args.limit]
        if not files:
            print("no supported files found")
            return

        if args.subject or args.collection_name:
            target_collection = resolve_collection_name(subject=args.subject, collection_name=args.collection_name)
            subject = normalize_subject(args.subject) or target_collection
            course_name = target_collection
            course_description = f"{subject} knowledge collection"
            agent = get_subject_agent(subject=args.subject, collection_name=target_collection)
        else:
            if not args.course:
                parser.error("--course is required when --subject or --collection-name is not provided")
            target_collection = ""
            subject = ""
            course_name = args.course
            course_description = "local ingest"
            agent = None

        course = db.query(Course).filter(Course.name == course_name).first()
        if not course:
            course = Course(name=course_name, description=course_description)
            db.add(course)
            db.commit()
            db.refresh(course)

        print(f"files: {len(files)}")
        for file_path in files:
            source_path = str(file_path.resolve())
            existing = db.query(Document).filter(Document.source_path == source_path).order_by(Document.id.desc()).first()
            if not args.force:
                if existing and existing.status == "indexed":
                    print(f"skip indexed {file_path}")
                    continue

            if existing and not args.force:
                document = existing
                document.course_id = course.id
                document.status = "pending"
                document.error_message = ""
                db.commit()
                db.refresh(document)
            else:
                document = Document(
                    course_id=course.id,
                    file_name=file_path.name,
                    source_path=source_path,
                    status="pending",
                )
                db.add(document)
                db.commit()
                db.refresh(document)
            try:
                if agent is None:
                    count = ingest_document(db, document)
                    collection_label = "default"
                else:
                    result = agent.ingest(db, document, collection_name=target_collection, subject=subject)
                    count = int(result.get("chunks", 0))
                    collection_label = target_collection
                print(f"indexed {file_path} -> {count} chunks [{collection_label}]")
            except Exception as exc:
                failures.append((file_path, str(exc)))
                print(f"failed {file_path}: {exc}")

        if failures:
            print("\nfailures:")
            for file_path, error in failures:
                print(f"- {file_path}: {error}")
            raise SystemExit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
