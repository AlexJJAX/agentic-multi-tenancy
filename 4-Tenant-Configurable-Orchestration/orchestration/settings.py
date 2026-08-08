"""Live OpenAI runtime settings for tenant orchestration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    """Load the model configuration used by normal workflow construction."""

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-5-mini"
    openai_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    def require_openai_api_key(self) -> str:
        """Return the live credential or reject normal workflow startup."""

        api_key = self.openai_api_key.strip()
        if not api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required because tenant-workflow uses a live OpenAI model. "
                "Automated tests must inject workflow doubles explicitly."
            )
        return api_key


settings = Settings()
