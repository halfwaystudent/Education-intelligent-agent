from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from app.core.config import get_settings

MAX_UPLOAD_BYTES = 50 * 1024 * 1024
READ_SIZE = 1024 * 1024


async def _write_upload(upload_file: UploadFile, target: Path) -> Path:
    total = 0
    try:
        with target.open("wb") as output:
            while chunk := await upload_file.read(READ_SIZE):
                total += len(chunk)
                if total > MAX_UPLOAD_BYTES:
                    raise HTTPException(status_code=413, detail="文件不能超过 50MB")
                output.write(chunk)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        await upload_file.seek(0)
    return target


async def save_upload_file(course_id: int, upload_file: UploadFile) -> Path:
    settings = get_settings()
    course_dir = settings.upload_dir / str(course_id)
    course_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(upload_file.filename or f"upload-{uuid4().hex}.txt").name
    target = course_dir / f"{uuid4().hex}-{safe_name}"
    return await _write_upload(upload_file, target)


async def save_collection_upload_file(upload_file: UploadFile, collection_name: str) -> Path:
    settings = get_settings()
    common_dir = settings.upload_dir / collection_name
    common_dir.mkdir(parents=True, exist_ok=True)
    safe_name = Path(upload_file.filename or f"upload-{uuid4().hex}.txt").name
    target = common_dir / f"{uuid4().hex}-{safe_name}"
    return await _write_upload(upload_file, target)


def resolve_document_file(source_path: str | Path, file_name: str = "") -> Path:
    """Resolve a persisted upload path after the project directory has moved."""
    candidate = Path(source_path)
    if candidate.exists():
        return candidate.resolve()

    safe_name = Path(file_name or candidate.name).name
    if not safe_name:
        raise FileNotFoundError(f"document source does not exist: {source_path}")

    upload_root = get_settings().upload_dir.resolve()
    matches = [path.resolve() for path in upload_root.rglob(safe_name) if path.is_file()]
    unique_matches = list(dict.fromkeys(matches))
    if len(unique_matches) == 1:
        return unique_matches[0]
    if not unique_matches:
        raise FileNotFoundError(f"document source does not exist: {source_path}")
    raise FileNotFoundError(f"multiple upload files match {safe_name}: {len(unique_matches)}")
