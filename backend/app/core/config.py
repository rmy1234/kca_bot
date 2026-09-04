from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "정보보안기사 AI 학습 프로그램 API"
    environment: str = "development"
    database_url: str = "sqlite+aiosqlite:///./kca_bot.db"
    llm_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
