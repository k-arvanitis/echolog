from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    data_dir: Path = Field(default=Path("data"), alias="MIE_DATA_DIR")
    output_dir: Path = Field(default=Path("outputs"), alias="MIE_OUTPUT_DIR")
    device: str = Field(default="auto", alias="MIE_DEVICE")
    groq_api_key: SecretStr | None = Field(default=None, alias="GROQ_API_KEY")
    asr_model_name: str = Field(default="whisper-large-v3", alias="MIE_ASR_MODEL_NAME")
    analytics_model_name: str = Field(default="llama-3.1-8b-instant", alias="MIE_ANALYTICS_MODEL_NAME")
    analytics_enabled: bool = Field(default=True, alias="MIE_ANALYTICS_ENABLED")
    rag_enabled: bool = Field(default=True, alias="MIE_RAG_ENABLED")
    rag_model_name: str = Field(default="llama-3.3-70b-versatile", alias="MIE_RAG_MODEL_NAME")
    openai_api_key: SecretStr | None = Field(default=None, alias="OPENAI_API_KEY")
    rag_eval_judge_model: str = Field(default="gpt-4.1-mini", alias="MIE_RAG_EVAL_JUDGE_MODEL")
    asr_chunk_seconds: int = Field(default=600, alias="MIE_ASR_CHUNK_SECONDS")
    language: str | None = Field(default="en", alias="MIE_LANGUAGE")
    diarization_model_name: str = Field(default="pyannote/speaker-diarization-3.1", alias="MIE_DIARIZATION_MODEL_NAME")
    hf_token: SecretStr | None = Field(default=None, alias="HF_TOKEN")
    max_upload_mb: int = Field(default=500, alias="MIE_MAX_UPLOAD_MB")
    max_duration_seconds: int = Field(default=14_400, alias="MIE_MAX_DURATION_SECONDS")
    api_host: str = Field(default="0.0.0.0", alias="MIE_API_HOST")
    api_port: int = Field(default=8001, alias="MIE_API_PORT")
    api_key: SecretStr | None = Field(default=None, alias="MIE_API_KEY")
    reload: bool = Field(default=False, alias="MIE_RELOAD")
    log_level: str = Field(default="INFO", alias="MIE_LOG_LEVEL")
    cors_allow_origins: list[str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        alias="MIE_CORS_ALLOW_ORIGINS",
    )
    database_url: str = Field(default="postgresql+psycopg://mie:mie@localhost:5432/mie", alias="DATABASE_URL")
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")
    celery_task_always_eager: bool = Field(default=False, alias="CELERY_TASK_ALWAYS_EAGER")
    qdrant_url: str = Field(default="http://localhost:6333", alias="QDRANT_URL")
    qdrant_api_key: SecretStr | None = Field(default=None, alias="QDRANT_API_KEY")
    qdrant_collection: str = Field(default="meeting_transcript_md", alias="QDRANT_COLLECTION")
    dense_model: str = Field(default="nomic-embed-text", alias="DENSE_MODEL")
    dense_dim: int = Field(default=768, alias="DENSE_DIM")
    sparse_model: str = Field(default="Qdrant/bm25", alias="SPARSE_MODEL")
    ui_title: str = Field(default="Meeting Intelligence Engine", alias="MIE_UI_TITLE")
    default_retention_days: int | None = Field(default=90, alias="MIE_DEFAULT_RETENTION_DAYS")
    delete_raw_audio_after_processing: bool = Field(default=False, alias="MIE_DELETE_RAW_AUDIO_AFTER_PROCESSING")

    def secret(self, name: str) -> str | None:
        """Return the plaintext value of a SecretStr setting, or None if unset."""
        value: SecretStr | None = getattr(self, name)
        return value.get_secret_value() if value is not None else None


settings = Settings()
