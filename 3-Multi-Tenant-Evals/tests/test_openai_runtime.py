"""Normal evaluation startup requires live OpenAI configuration."""

from __future__ import annotations

import pytest

from eval_harness.settings import Settings


def test_openai_api_key_is_required() -> None:
    settings = Settings(_env_file=None, openai_api_key="")
    with pytest.raises(RuntimeError, match="tenant-evals uses live OpenAI models"):
        settings.require_openai_api_key()


def test_configured_openai_api_key_is_returned() -> None:
    settings = Settings(_env_file=None, openai_api_key="injected-test-only-key")
    assert settings.require_openai_api_key() == "injected-test-only-key"
