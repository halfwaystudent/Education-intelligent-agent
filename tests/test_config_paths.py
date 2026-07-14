from pathlib import Path

from app.core.config import PROJECT_ROOT, Settings


def test_settings_paths_are_project_relative_from_any_working_directory(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    settings = Settings(
        _env_file=None,
        database_url="sqlite:///./data/app.db",
        upload_dir=Path("./data/uploads"),
        chroma_dir=Path("./data/chroma"),
        question_render_dir=Path("./data/question_rendered"),
    )
    assert settings.database_url == f"sqlite:///{(PROJECT_ROOT / 'data/app.db').as_posix()}"
    assert settings.chroma_dir == (PROJECT_ROOT / "data/chroma").resolve()
    assert settings.upload_dir == (PROJECT_ROOT / "data/uploads").resolve()
    assert settings.question_render_dir == (PROJECT_ROOT / "data/question_rendered").resolve()
