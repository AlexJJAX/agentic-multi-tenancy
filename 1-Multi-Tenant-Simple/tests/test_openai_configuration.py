"""OpenAI runtime configuration requirements."""

from unittest.mock import AsyncMock, patch

import pytest

from app.config import Settings, settings
from app.main import app, lifespan


@pytest.mark.parametrize(
    "api_key",
    ["", "   ", "your-openai-api-key-here"],
)
def test_openai_api_key_is_required(api_key: str) -> None:
    configured = Settings(openai_api_key=api_key)

    with pytest.raises(RuntimeError, match="OPENAI_API_KEY must be set"):
        configured.require_openai_api_key()


def test_configured_openai_api_key_is_returned() -> None:
    configured = Settings(openai_api_key="sk-test-only")

    assert configured.require_openai_api_key() == "sk-test-only"


def test_offline_environment_flag_cannot_bypass_key_requirement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OFFLINE_MODE", "true")
    configured = Settings(openai_api_key="", _env_file=None)

    assert not hasattr(configured, "offline_mode")
    with pytest.raises(RuntimeError, match="Offline mode is not supported"):
        configured.require_openai_api_key()


@pytest.mark.asyncio
async def test_startup_rejects_missing_openai_key_before_initialization() -> None:
    with (
        patch.object(settings, "openai_api_key", ""),
        patch("app.main.init_db", new_callable=AsyncMock) as init_db,
    ):
        with pytest.raises(RuntimeError, match="Offline mode is not supported"):
            async with lifespan(app):
                pass

    init_db.assert_not_awaited()
