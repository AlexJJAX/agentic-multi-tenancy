"""Strict tenant agent configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

ToolName = Literal["query_orders", "query_rag", "calculator"]
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class TenantAgentConfig(BaseModel):
    """Immutable behavior and capability declaration for one tenant."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tenant_id: str = Field(pattern=r"^tenant-[A-Z]$")
    persona: str = Field(min_length=10, max_length=300)
    allowed_tools: tuple[ToolName, ...] = Field(min_length=1)
    guardrails: tuple[str, ...] = Field(min_length=1)
    require_plan_approval: bool = True

    @field_validator("allowed_tools")
    @classmethod
    def unique_tools(cls, value: tuple[ToolName, ...]) -> tuple[ToolName, ...]:
        if len(value) != len(set(value)):
            raise ValueError("allowed_tools cannot contain duplicates")
        return value


def load_tenant_config(tenant_id: str, config_root: Path | None = None) -> TenantAgentConfig:
    """Load exactly the authenticated tenant's configuration and verify ownership."""

    root = config_root or PROJECT_ROOT / "config"
    path = root / tenant_id / "agent.yaml"
    if not path.is_file():
        raise ValueError("No active agent configuration exists for this tenant")
    config = TenantAgentConfig.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    if config.tenant_id != tenant_id:
        raise ValueError("Agent configuration tenant does not match authenticated tenant")
    return config
