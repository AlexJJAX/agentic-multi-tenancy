"""Normal graph construction requires the live OpenAI runtime."""

from __future__ import annotations

import pytest

from orchestration.graph import Principal, build_tenant_workflow
from orchestration.settings import Settings


def test_openai_api_key_is_required_without_injected_dependencies() -> None:
    app_settings = Settings(_env_file=None, openai_api_key="")
    with pytest.raises(RuntimeError, match="tenant-workflow uses a live OpenAI model"):
        build_tenant_workflow(
            Principal(user_id="alice", tenant_id="tenant-A"),
            app_settings=app_settings,
        )


def test_configured_openai_api_key_is_returned() -> None:
    app_settings = Settings(_env_file=None, openai_api_key="injected-test-only-key")
    assert app_settings.require_openai_api_key() == "injected-test-only-key"
