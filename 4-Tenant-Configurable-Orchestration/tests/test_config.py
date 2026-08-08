"""Configuration ownership is a security boundary."""

from __future__ import annotations

from pathlib import Path

import pytest

from orchestration.config import load_tenant_config


def test_config_tenant_must_match_directory(tmp_path: Path) -> None:
    path = tmp_path / "tenant-A"
    path.mkdir()
    (path / "agent.yaml").write_text(
        """
tenant_id: tenant-B
persona: A sufficiently descriptive test persona.
allowed_tools: [query_rag]
guardrails: [Read only.]
require_plan_approval: true
""".strip(),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="does not match"):
        load_tenant_config("tenant-A", tmp_path)
