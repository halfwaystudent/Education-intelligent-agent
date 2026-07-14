from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "Education Intelligent Agent"
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    chat_model: str = "gpt-4o-mini"
    embedding_provider: str = "local"
    embedding_model: str = "text-embedding-3-small"
    local_embedding_model: str = "BAAI/bge-m3"
    local_embedding_max_seq_length: int = 2048
    embedding_max_chars: int = 6000

    database_url: str = "sqlite:///./data/app.db"
    upload_dir: Path = Path("./data/uploads")
    chroma_dir: Path = Path("./data/chroma")
    chroma_collection: str = "course_chunks_bge_m3"
    chunk_size: int = 900
    chunk_overlap: int = 120
    retrieval_top_k: int = 5
    retrieval_min_score: float = 0.50
    retrieval_candidate_multiplier: int = 4
    retrieval_max_per_material: int = 1
    retrieval_max_per_document: int = 2

    question_render_ocr_enabled: bool = True
    question_render_ocr_image_only: bool = True
    question_render_dpi_scale: int = 2
    question_render_width: int = 960
    question_render_dir: Path = Path("./data/question_rendered")

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
    )

    @model_validator(mode="after")
    def resolve_project_paths(self):
        self.upload_dir = _project_path(self.upload_dir)
        self.chroma_dir = _project_path(self.chroma_dir)
        self.question_render_dir = _project_path(self.question_render_dir)
        self.database_url = _project_database_url(self.database_url)
        return self


def _project_path(value: Path) -> Path:
    return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()


def _project_database_url(value: str) -> str:
    prefix = "sqlite:///"
    if not value.startswith(prefix):
        return value
    raw_path = value[len(prefix):]
    if raw_path == ":memory:":
        return value
    path = Path(raw_path)
    if not path.is_absolute():
        path = (PROJECT_ROOT / path).resolve()
    return f"{prefix}{path.as_posix()}"


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    settings.chroma_dir.mkdir(parents=True, exist_ok=True)
    settings.question_render_dir.mkdir(parents=True, exist_ok=True)
    return settings
