from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.chat import router as chat_router
from app.api.collections import router as collections_router
from app.api.courses import router as courses_router
from app.api.documents import router as documents_router
from app.api.papers import router as papers_router
from app.api.upload import router as upload_router
from app.core.config import get_settings
from app.models.db import init_db
from app.rag.image_ocr import DISPLAY_IMAGE_DIR

settings = get_settings()
app = FastAPI(title=settings.app_name)
PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_DIST = PROJECT_ROOT / "frontend" / "dist"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/api/health")
def health_check():
    return {"status": "ok", "app": settings.app_name}


DISPLAY_IMAGE_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/media/formulas", StaticFiles(directory=DISPLAY_IMAGE_DIR), name="formula-media")
question_image_dir = settings.question_render_dir / "images"
question_image_dir.mkdir(parents=True, exist_ok=True)
app.mount("/media/questions", StaticFiles(directory=question_image_dir), name="question-media")
REPORT_DIR = PROJECT_ROOT / "data" / "reports"
REPORT_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/reports", StaticFiles(directory=REPORT_DIR, html=True), name="reports")

app.include_router(courses_router)
app.include_router(documents_router)
app.include_router(upload_router)
app.include_router(papers_router)
app.include_router(chat_router)
app.include_router(collections_router)

if (FRONTEND_DIST / "assets").exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="frontend-assets")


def _frontend_index() -> Path:
    built = FRONTEND_DIST / "index.html"
    if built.exists():
        return built
    raise HTTPException(status_code=503, detail="前端尚未构建，请在 frontend 目录执行 pnpm build")


@app.get("/", include_in_schema=False)
def frontend_root():
    return FileResponse(_frontend_index())


@app.get("/{full_path:path}", include_in_schema=False)
def frontend_spa(full_path: str):
    if full_path.startswith(("api/", "media/", "reports/")):
        raise HTTPException(status_code=404, detail="资源不存在")
    candidate = (FRONTEND_DIST / full_path).resolve()
    try:
        candidate.relative_to(FRONTEND_DIST.resolve())
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="资源不存在") from exc
    if candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(_frontend_index())


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.app_host, port=settings.app_port, reload=True)
