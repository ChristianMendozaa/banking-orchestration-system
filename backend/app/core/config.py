from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str
    bank_name: str
    branch_name: str
    api_v1_prefix: str = "/api/v1"
    database_url: str
    database_migration_url: str | None = None
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr = SecretStr("")

    openai_api_key: SecretStr = SecretStr("")
    voice_model: str = "gpt-realtime-2.1-mini"
    transcription_model: str = "gpt-realtime-whisper"
    orchestration_model: str = "gpt-5.4-mini"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    realtime_voice: str = "marin"

    rag_top_k: int = 5
    rag_min_score: float = 0.45
    rag_max_context_tokens: int = 3000
    rag_chunk_tokens: int = 600
    rag_chunk_overlap: int = 100
    rag_corpus_dir: str = "../doc/rag"

    jwt_secret: SecretStr
    identifier_pepper: SecretStr
    cors_origins: Annotated[list[str], NoDecode]
    access_token_minutes: int = 30
    refresh_token_hours: int = 8
    kiosk_session_minutes: int = 30
    seed_executive_password: SecretStr
    seed_manager_password: SecretStr
    seed_data_path: str = "seed/demo_seed.json"
    dashboard_refresh_ms: int = 10_000

    knowledge_storage_dir: str = "../data/knowledge"
    knowledge_seed_dir: str = "../doc/rag"
    knowledge_max_upload_mb: int = 20
    knowledge_max_pages: int = 300

    classification_confidence_threshold: float = 0.68
    max_clarifications: int = 2
    openai_timeout_seconds: float = 20.0

    @model_validator(mode="after")
    def validate_rag_settings(self) -> "Settings":
        if self.embedding_dimensions <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS debe ser positivo")
        if self.rag_top_k <= 0:
            raise ValueError("RAG_TOP_K debe ser positivo")
        if not 0 <= self.rag_min_score <= 1:
            raise ValueError("RAG_MIN_SCORE debe estar entre 0 y 1")
        if self.rag_chunk_tokens < 100:
            raise ValueError("RAG_CHUNK_TOKENS debe ser al menos 100")
        if not 0 <= self.rag_chunk_overlap < self.rag_chunk_tokens:
            raise ValueError("RAG_CHUNK_OVERLAP debe ser menor que RAG_CHUNK_TOKENS")
        if self.embedding_dimensions != 1536:
            raise ValueError(
                "EMBEDDING_DIMENSIONS debe ser 1536 porque el esquema pgvector usa esa dimension"
            )
        if self.kiosk_session_minutes <= 0:
            raise ValueError("KIOSK_SESSION_MINUTES debe ser positivo")
        if self.knowledge_max_upload_mb <= 0:
            raise ValueError("KNOWLEDGE_MAX_UPLOAD_MB debe ser positivo")
        if self.knowledge_max_pages <= 0:
            raise ValueError("KNOWLEDGE_MAX_PAGES debe ser positivo")
        if self.dashboard_refresh_ms < 1_000:
            raise ValueError("DASHBOARD_REFRESH_MS debe ser al menos 1000")
        return self

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_security_secrets(self) -> "Settings":
        jwt_secret = self.jwt_secret.get_secret_value()
        pepper = self.identifier_pepper.get_secret_value()
        executive_password = self.seed_executive_password.get_secret_value()
        manager_password = self.seed_manager_password.get_secret_value()
        if len(jwt_secret) < 32:
            raise ValueError("JWT_SECRET debe ser un secreto aleatorio de al menos 32 caracteres")
        if len(pepper) < 32:
            raise ValueError(
                "IDENTIFIER_PEPPER debe ser un secreto aleatorio de al menos 32 caracteres"
            )
        if len(executive_password) < 12 or len(manager_password) < 12:
            raise ValueError("Las contrasenas de semilla deben tener al menos 12 caracteres")
        if self.app_env == "production" and not self.openai_enabled:
            raise ValueError("OPENAI_API_KEY es obligatorio en produccion")
        return self

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
