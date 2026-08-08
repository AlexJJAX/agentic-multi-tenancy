"""Application settings and project-local path resolution."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Configuration loaded from environment variables or the project ``.env`` file."""

    openai_api_key: str = ""
    openai_chat_model: str = "gpt-5-mini"
    openai_embedding_model: str = "text-embedding-3-small"

    app_base_url: str = "http://localhost:8000"
    identity_issuer: str = "http://localhost:8000"
    session_secret: str = ""

    gateway_mcp_url: str = "http://127.0.0.1:8000/mcp"
    orders_target_url: str = "http://127.0.0.1:8000/internal/tools/orders"
    tvm_url: str = "http://127.0.0.1:8000/internal/tvm"
    properties_mcp_url: str = "http://127.0.0.1:8000/internal/mcp/properties"

    gateway_service_client_id: str = "mcp-gateway-service"
    gateway_service_client_secret: str = ""
    orders_service_client_id: str = "orders-target-service"
    orders_service_client_secret: str = ""

    gateway_capability_private_key_path: Path = Path(".local/keys/gateway_private.pem")
    gateway_capability_public_key_path: Path = Path(".local/keys/gateway_public.pem")
    identity_private_key_path: Path = Path(".local/keys/identity_private.pem")
    identity_public_key_path: Path = Path(".local/keys/identity_public.pem")
    sqlite_path: Path = Path(".local/demo.db")

    chroma_persist: bool = False
    dev_auto_migrate: bool = True
    dev_auto_seed: bool = True
    dev_generate_keys: bool = True
    testing: bool = False
    log_level: str = "INFO"
    enable_debug_trace: bool = True

    user_token_ttl_seconds: int = Field(default=1800, ge=60, le=86400)
    service_token_ttl_seconds: int = Field(default=300, ge=60, le=3600)
    session_ttl_seconds: int = Field(default=28800, ge=300, le=86400)
    capability_ttl_seconds: int = Field(default=60, ge=5, le=60)
    store_credential_ttl_seconds: int = Field(default=45, ge=5, le=60)
    retrieval_top_k: int = Field(default=4, ge=1, le=10)
    history_max_messages: int = Field(default=10, ge=1, le=50)
    internal_timeout_seconds: float = Field(default=3.0, gt=0, le=30)
    openai_timeout_seconds: float = Field(default=30.0, gt=0, le=120)

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @field_validator(
        "gateway_capability_private_key_path",
        "gateway_capability_public_key_path",
        "identity_private_key_path",
        "identity_public_key_path",
        "sqlite_path",
        mode="after",
    )
    @classmethod
    def resolve_project_path(cls, value: Path) -> Path:
        """Resolve relative runtime paths beneath the project root."""

        return value if value.is_absolute() else PROJECT_ROOT / value

    @property
    def runtime_dir(self) -> Path:
        """Return the generated local runtime directory."""

        return self.sqlite_path.parent

    @property
    def knowledge_dir(self) -> Path:
        """Return the checked-in tenant knowledge directory."""

        return PROJECT_ROOT / "knowledge"

    def validate_runtime_requirements(self) -> None:
        """Fail startup when the required live OpenAI credential is absent."""

        if not self.openai_api_key.strip():
            raise RuntimeError(
                "OPENAI_API_KEY is required because runtime always uses live OpenAI models. "
                "Automated tests must inject model and embedding doubles explicitly."
            )


settings = Settings()
