"""
Application configuration module.

Loads settings from environment variables with sensible defaults.
Uses pydantic-settings for validation and python-dotenv for .env file loading.
"""

from pathlib import Path

from dotenv import load_dotenv
from pydantic_settings import BaseSettings, SettingsConfigDict

# Explicit process/CI settings take precedence over project-local development defaults.
load_dotenv(override=False)

# Project root is two levels up from this file (app/config.py -> project root)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
OPENAI_API_KEY_PLACEHOLDER = "your-openai-api-key-here"


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # --- OpenAI ---
    openai_api_key: str = ""

    # --- Models ---
    chat_model: str = "gpt-5-mini"
    embedding_model: str = "text-embedding-3-small"
    query_rewrite_model: str = "gpt-5-mini"
    query_rewrite_enabled: bool = True

    # --- Database ---
    sqlite_path: str = "data/demo.sqlite3"

    # --- Knowledge Base ---
    kb_root: str = "data/kb"

    # --- ChromaDB ---
    chroma_mode: str = "in-memory"
    chroma_persist_path: str = "data/chroma"

    # --- Retrieval ---
    retrieval_top_k: int = 4

    # --- JWT Authentication ---
    jwt_secret_key: str = ""  # MUST be set in .env; left empty to fail fast on sign
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 480  # 8 hours — suitable for a dev demo

    # --- Chat History ---
    chat_history_max_messages: int = 8

    # --- Server ---
    app_host: str = "127.0.0.1"
    app_port: int = 8000

    # --- LangSmith (optional) ---
    langsmith_api_key: str = ""
    langsmith_tracing: bool = True
    langsmith_endpoint: str = "https://eu.api.smith.langchain.com"
    langsmith_project: str = "multi-tenant-rag-chatbot"

    @property
    def sqlite_url(self) -> str:
        """Get the full SQLite connection URL for SQLAlchemy."""
        db_path = PROJECT_ROOT / self.sqlite_path
        return f"sqlite+aiosqlite:///{db_path}"

    @property
    def sqlite_sync_url(self) -> str:
        """Get the synchronous SQLite connection URL (for LangChain chat history)."""
        db_path = PROJECT_ROOT / self.sqlite_path
        return f"sqlite:///{db_path}"

    @property
    def kb_root_path(self) -> Path:
        """Get the absolute path to the knowledge base root directory."""
        return PROJECT_ROOT / self.kb_root

    @property
    def chroma_persist_path_resolved(self) -> Path:
        """Get the project-local directory used by persistent Chroma mode."""
        return PROJECT_ROOT / self.chroma_persist_path

    def require_openai_api_key(self) -> str:
        """Return the configured OpenAI API key or fail with setup guidance."""
        api_key = self.openai_api_key.strip()
        if not api_key or api_key == OPENAI_API_KEY_PLACEHOLDER:
            raise RuntimeError(
                "OPENAI_API_KEY must be set to a valid OpenAI API key. "
                "Offline mode is not supported by 1-Multi-Tenant-Simple."
            )
        return api_key

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Singleton settings instance
settings = Settings()
