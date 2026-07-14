from __future__ import annotations

from sqlalchemy import Engine, inspect, text

SCHEMA_VERSION = 1


def _column_names(engine: Engine, table_name: str) -> set[str]:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return set()
    return {column["name"] for column in inspector.get_columns(table_name)}


def run_db_migrations(engine: Engine) -> None:
    """Run small, versioned SQLite-compatible migrations before create_all()."""
    with engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE IF NOT EXISTS schema_migrations ("
                "version INTEGER PRIMARY KEY, applied_at DATETIME DEFAULT CURRENT_TIMESTAMP)"
            )
        )
        applied = {
            int(row[0])
            for row in connection.execute(text("SELECT version FROM schema_migrations")).fetchall()
        }

    if 1 not in applied:
        session_columns = _column_names(engine, "chat_sessions")
        message_columns = _column_names(engine, "chat_messages")
        with engine.begin() as connection:
            if session_columns:
                additions = {
                    "title": "VARCHAR(200) DEFAULT ''",
                    "subject": "VARCHAR(30) DEFAULT ''",
                    "collection_name": "VARCHAR(80) DEFAULT ''",
                    "updated_at": "DATETIME",
                }
                for name, ddl in additions.items():
                    if name not in session_columns:
                        connection.execute(text(f"ALTER TABLE chat_sessions ADD COLUMN {name} {ddl}"))
                connection.execute(
                    text("UPDATE chat_sessions SET updated_at = created_at WHERE updated_at IS NULL")
                )
            if message_columns and "confidence" not in message_columns:
                connection.execute(
                    text("ALTER TABLE chat_messages ADD COLUMN confidence VARCHAR(20) DEFAULT ''")
                )
            connection.execute(text("INSERT INTO schema_migrations(version) VALUES (1)"))
