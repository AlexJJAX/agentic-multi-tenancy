"""Global safeguards for API-free automated tests."""

from __future__ import annotations

import pytest

from app.config import settings


@pytest.fixture(autouse=True)
def clear_live_openai_credential(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove every test passes without the developer's live OpenAI key."""

    monkeypatch.setattr(settings, "openai_api_key", "")
