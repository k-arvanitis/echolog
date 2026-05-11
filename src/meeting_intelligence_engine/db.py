from __future__ import annotations

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from meeting_intelligence_engine.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {"check_same_thread": False} if settings.database_url.startswith("sqlite") else {}
engine = create_engine(settings.database_url, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def init_db() -> None:
    import meeting_intelligence_engine.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    add_missing_columns()


def add_missing_columns() -> None:
    inspector = inspect(engine)
    table_names = inspector.get_table_names()
    if "meetings" not in table_names:
        return
    columns = {column["name"] for column in inspector.get_columns("meetings")}
    statements = []
    if "processing_stage" not in columns:
        statements.append("ALTER TABLE meetings ADD COLUMN processing_stage VARCHAR(64) NOT NULL DEFAULT 'uploaded'")
    if "progress_percent" not in columns:
        statements.append("ALTER TABLE meetings ADD COLUMN progress_percent FLOAT NOT NULL DEFAULT 0.0")
    if "transcript_md_path" not in columns:
        statements.append("ALTER TABLE meetings ADD COLUMN transcript_md_path TEXT")
    if "retention_until" not in columns:
        statements.append("ALTER TABLE meetings ADD COLUMN retention_until TIMESTAMP")
    if "raw_audio_deleted_at" not in columns:
        statements.append("ALTER TABLE meetings ADD COLUMN raw_audio_deleted_at TIMESTAMP")
    if "transcripts" in table_names:
        transcript_columns = {column["name"] for column in inspector.get_columns("transcripts")}
        if "speaker_name" not in transcript_columns:
            statements.append("ALTER TABLE transcripts ADD COLUMN speaker_name VARCHAR(255)")
    if not statements:
        return
    with engine.begin() as connection:
        for statement in statements:
            connection.execute(text(statement))
