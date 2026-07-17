from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "Sistema de Orquestacion Bancaria"
    api_v1_prefix: str = "/api/v1"
    database_url: str = "postgresql+psycopg://orquestacion:orquestacion@localhost:5432/orquestacion"
    database_migration_url: str | None = None
    supabase_url: str | None = None
    supabase_service_role_key: SecretStr = SecretStr("")

    openai_api_key: SecretStr = SecretStr("")
    voice_model: str = "gpt-realtime-2.1-mini"
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

    jwt_secret: SecretStr = SecretStr("development-only-secret-change-me-32-chars")
    identifier_pepper: SecretStr = SecretStr("development-only-pepper-change-me")
    cors_origins: list[str] = Field(default_factory=lambda: ["http://localhost:3000"])
    access_token_minutes: int = 30
    refresh_token_hours: int = 8
    seed_executive_password: SecretStr = SecretStr("ChangeMe-Executive-2026")
    seed_manager_password: SecretStr = SecretStr("ChangeMe-Manager-2026")

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
        return self

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @model_validator(mode="after")
    def validate_production_secrets(self) -> "Settings":
        if self.app_env != "production":
            return self
        jwt_secret = self.jwt_secret.get_secret_value()
        pepper = self.identifier_pepper.get_secret_value()
        if len(jwt_secret) < 32 or "development-only" in jwt_secret:
            raise ValueError("JWT_SECRET debe ser un secreto aleatorio de al menos 32 caracteres")
        if len(pepper) < 32 or "development-only" in pepper:
            raise ValueError(
                "IDENTIFIER_PEPPER debe ser un secreto aleatorio de al menos 32 caracteres"
            )
        if not self.openai_enabled:
            raise ValueError("OPENAI_API_KEY es obligatorio en produccion")
        if "ChangeMe" in self.seed_executive_password.get_secret_value() or "ChangeMe" in (
            self.seed_manager_password.get_secret_value()
        ):
            raise ValueError("Las contrasenas de semilla deben cambiarse en produccion")
        return self

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
