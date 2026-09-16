from functools import lru_cache
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

INSECURE_JWT_SECRET = "dev-insecure-change-me"


class Settings(BaseSettings):
    app_name: str = "정보보안기사 AI 학습 프로그램 API"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./kca_bot.db"
    gemini_api_key: str | None = None
    llm_model: str = "gemini-3.6-flash"
    # "gemini" (uses the mock generator when GEMINI_API_KEY is empty) or "ollama" for a local model.
    llm_provider: Literal["gemini", "ollama"] = "gemini"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen3.5:9b"
    # Must hold the prompt plus the generated JSON; larger values use more VRAM.
    ollama_num_ctx: int = 16384
    ollama_think: bool = False
    ollama_timeout_seconds: float = 600.0
    # Used automatically while OLLAMA_MODEL (e.g. a cloud model) is over its usage limit; the primary is retried after the cooldown.
    ollama_fallback_model: str | None = None
    ollama_fallback_minutes: int = 60
    # Models offered in the question-generation model picker, as "provider:model" entries.
    # Gemini entries are hidden while GEMINI_API_KEY is empty.
    # Each Gemini model has its own free-tier daily allowance, so several are offered to switch between.
    selectable_models: list[str] = [
        "gemini:gemini-3.6-flash",
        "gemini:gemini-3.5-flash",
        "gemini:gemini-3.5-flash-lite",
        "gemini:gemini-3-flash-preview",
        "gemini:gemini-3.1-flash-lite",
        "ollama:qwen3.5:9b",
        "ollama:qwen3.5:4b",
    ]
    # Self-service signup is off by default: an open form on a reachable port lets anyone create an
    # account and spend LLM quota. Turn it on only while you actually need to add a learner.
    registration_open: bool = False
    # Per-user cap on the endpoints that call the LLM, so one account cannot drain the daily quota.
    llm_requests_per_hour: int = 30
    jwt_secret_key: str = INSECURE_JWT_SECRET
    jwt_algorithm: str = "HS256"
    jwt_expire_minutes: int = 60 * 24 * 7
    admin_email: str | None = None
    admin_password: str | None = None
    # Set as a JSON list in .env, e.g. CORS_ORIGINS=["http://localhost:5173"].
    cors_origins: list[str] = ["http://localhost:5173"]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @model_validator(mode="after")
    def require_real_jwt_secret_outside_development(self):
        # Anyone who knows the published default could forge login tokens on a deployed server.
        if self.environment != "development" and self.jwt_secret_key == INSECURE_JWT_SECRET:
            raise ValueError("JWT_SECRET_KEY must be set to a long random value when ENVIRONMENT is not development.")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
