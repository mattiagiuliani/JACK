from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "JACK API"
    app_version: str = "0.1.0"
    environment: str = "development"

    research_provider: Literal["controlled", "wikipedia", "crossref"] = "controlled"
    research_language: Literal["en", "it", "de", "fr", "es"] = "en"
    research_user_agent: str = ""
    research_timeout: float = Field(default=8, ge=1, le=30)
    research_interval: float = Field(default=1, ge=1, le=60)
    research_retries: int = Field(default=1, ge=0, le=2)
    research_max_results: int = Field(default=3, ge=1, le=5)

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
