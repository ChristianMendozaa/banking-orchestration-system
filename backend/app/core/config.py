import base64
import ipaddress
import json
import os
from functools import lru_cache
from typing import Annotated, Literal

from pydantic import SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# tests/conftest.py sets APP_ENV=test before importing this module and provides every
# setting the suite needs via os.environ. Loading .env on top of that would let a
# developer's local REDIS_URL / CLAMAV_HOST leak into the test process -- swapping in a
# real RedisRateLimiter or a real malware scan instead of the in-memory/no-op fallbacks
# the tests assume -- so tests must see the same clean environment CI does (no .env file
# exists on the runner).
_ENV_FILE = None if os.getenv("APP_ENV") == "test" else ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=_ENV_FILE, env_file_encoding="utf-8", extra="ignore", case_sensitive=False
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_name: str
    bank_name: str
    branch_name: str
    api_v1_prefix: str = "/api/v1"
    database_url: str
    database_migration_url: str | None = None
    supabase_url: str | None = None
    redis_url: str | None = None
    trusted_proxy_cidrs: Annotated[list[str], NoDecode] = []
    metrics_token: SecretStr = SecretStr("")

    openai_api_key: SecretStr = SecretStr("")
    voice_model: str = "gpt-realtime-2.1"
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
    identifier_encryption_keys: Annotated[dict[str, str], NoDecode] = {
        "development-v1": "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
    }
    identifier_active_key_id: str = "development-v1"
    conversation_retention_days: int = 90
    conversation_cleanup_hours: int = 24
    cors_origins: Annotated[list[str], NoDecode]
    access_token_minutes: int = 30
    refresh_token_hours: int = 8
    kiosk_session_minutes: int = 30
    seed_executive_password: SecretStr
    seed_manager_password: SecretStr
    seed_data_path: str = "seed/operational_seed.json"
    dashboard_refresh_ms: int = 10_000

    knowledge_storage_dir: str = "../data/knowledge"
    knowledge_max_upload_mb: int = 20
    knowledge_max_pages: int = 300
    clamav_host: str | None = None
    clamav_port: int = 3310
    clamav_timeout_seconds: float = 15.0

    classification_confidence_threshold: float = 0.68
    max_clarifications: int = 2
    # How many times a customer may reject the summary before the kiosk stops re-asking
    # and hands the session to a person. Without a ceiling, a customer who cannot phrase
    # the request loops CONFIRM -> reject -> CAPTURE forever and leaves with no ticket.
    max_corrections: int = 2
    openai_timeout_seconds: float = 20.0
    estimated_service_minutes: int = 8
    support_tracking_information: str = (
        "Conserva tu número de ticket. Para seguimiento, utiliza los canales oficiales "
        "de atención de la entidad."
    )

    @model_validator(mode="after")
    def validate_rag_settings(self) -> "Settings":
        if self.embedding_dimensions <= 0:
            raise ValueError("EMBEDDING_DIMENSIONS must be positive")
        if self.rag_top_k <= 0:
            raise ValueError("RAG_TOP_K must be positive")
        if not 0 <= self.rag_min_score <= 1:
            raise ValueError("RAG_MIN_SCORE must be between 0 and 1")
        if self.rag_chunk_tokens < 100:
            raise ValueError("RAG_CHUNK_TOKENS must be at least 100")
        if not 0 <= self.rag_chunk_overlap < self.rag_chunk_tokens:
            raise ValueError("RAG_CHUNK_OVERLAP must be smaller than RAG_CHUNK_TOKENS")
        if self.embedding_dimensions != 1536:
            raise ValueError(
                "EMBEDDING_DIMENSIONS must be 1536 because the pgvector schema uses that dimension"
            )
        if self.kiosk_session_minutes <= 0:
            raise ValueError("KIOSK_SESSION_MINUTES must be positive")
        if self.knowledge_max_upload_mb <= 0:
            raise ValueError("KNOWLEDGE_MAX_UPLOAD_MB must be positive")
        if self.knowledge_max_pages <= 0:
            raise ValueError("KNOWLEDGE_MAX_PAGES must be positive")
        if not 1 <= self.clamav_port <= 65535:
            raise ValueError("CLAMAV_PORT must be a valid port")
        if self.clamav_timeout_seconds <= 0:
            raise ValueError("CLAMAV_TIMEOUT_SECONDS must be positive")
        if self.dashboard_refresh_ms < 1_000:
            raise ValueError("DASHBOARD_REFRESH_MS must be at least 1000")
        if self.estimated_service_minutes <= 0:
            raise ValueError("ESTIMATED_SERVICE_MINUTES must be positive")
        if self.conversation_retention_days <= 0:
            raise ValueError("CONVERSATION_RETENTION_DAYS must be positive")
        if self.conversation_cleanup_hours <= 0:
            raise ValueError("CONVERSATION_CLEANUP_HOURS must be positive")
        if not self.support_tracking_information.strip():
            raise ValueError("SUPPORT_TRACKING_INFORMATION cannot be empty")
        return self

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, value: str | list[str]) -> list[str]:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @field_validator("trusted_proxy_cidrs", mode="before")
    @classmethod
    def parse_trusted_proxy_cidrs(cls, value: str | list[str]) -> list[str]:
        parsed = [item.strip() for item in value.split(",")] if isinstance(value, str) else value
        result = [item for item in parsed if item]
        for item in result:
            ipaddress.ip_network(item, strict=False)
        return result

    @field_validator("identifier_encryption_keys", mode="before")
    @classmethod
    def parse_identifier_keys(cls, value: str | dict[str, str]) -> dict[str, str]:
        parsed = json.loads(value) if isinstance(value, str) else value
        if not isinstance(parsed, dict) or not parsed:
            raise ValueError("IDENTIFIER_ENCRYPTION_KEYS must be a non-empty JSON object")
        return {str(key): str(secret) for key, secret in parsed.items()}

    @model_validator(mode="after")
    def validate_security_secrets(self) -> "Settings":
        jwt_secret = self.jwt_secret.get_secret_value()
        pepper = self.identifier_pepper.get_secret_value()
        executive_password = self.seed_executive_password.get_secret_value()
        manager_password = self.seed_manager_password.get_secret_value()
        if len(jwt_secret) < 32:
            raise ValueError("JWT_SECRET must be a random secret of at least 32 characters")
        if len(pepper) < 32:
            raise ValueError("IDENTIFIER_PEPPER must be a random secret of at least 32 characters")
        if self.identifier_active_key_id not in self.identifier_encryption_keys:
            raise ValueError(
                "IDENTIFIER_ACTIVE_KEY_ID does not exist in IDENTIFIER_ENCRYPTION_KEYS"
            )
        for key_id, encoded in self.identifier_encryption_keys.items():
            try:
                decoded = base64.b64decode(encoded, validate=True)
            except ValueError as exc:
                raise ValueError(f"Invalid encryption key: {key_id}") from exc
            if len(decoded) != 32:
                raise ValueError(f"Encryption key {key_id} must contain 32 bytes")
        if self.app_env == "production" and "development-v1" in self.identifier_encryption_keys:
            raise ValueError("Configure an identifier keyring exclusive to production")
        if len(executive_password) < 12 or len(manager_password) < 12:
            raise ValueError("Seed passwords must be at least 12 characters long")
        if self.app_env == "production" and not self.openai_enabled:
            raise ValueError("OPENAI_API_KEY is required in production")
        if self.app_env == "production" and not self.redis_url:
            raise ValueError("REDIS_URL is required in production")
        if self.app_env == "production" and not self.clamav_host:
            raise ValueError("CLAMAV_HOST is required in production")
        if self.app_env == "production" and len(self.metrics_token.get_secret_value()) < 32:
            raise ValueError("METRICS_TOKEN must be at least 32 characters in production")
        return self

    @property
    def openai_enabled(self) -> bool:
        return bool(self.openai_api_key.get_secret_value().strip())


@lru_cache
def get_settings() -> Settings:
    return Settings()
