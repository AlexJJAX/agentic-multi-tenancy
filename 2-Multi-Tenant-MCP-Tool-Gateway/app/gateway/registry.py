"""Validated, read-only gateway target registry."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.settings import PROJECT_ROOT

ALLOWED_TOOLS = {"query_orders", "query_properties"}
ALLOWED_HEADERS = {"x-tenant-id", "x-tenant-context", "x-user-token", "x-request-id"}


class TargetDefinition(BaseModel):
    """One statically configured downstream target."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    target_type: Literal["lambda", "mcp"]
    path: str = Field(pattern=r"^/internal/")
    auth_mode: Literal["gateway_service", "service_plus_user_context"]
    timeout_seconds: float = Field(gt=0, le=30)
    propagated_headers: tuple[str, ...]

    @field_validator("propagated_headers")
    @classmethod
    def headers_are_allowlisted(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Reject registry entries that could propagate arbitrary client headers."""

        if not set(values) <= ALLOWED_HEADERS:
            raise ValueError("Target contains a non-allowlisted propagated header")
        return values


class TargetRegistry:
    """Resolve exactly the two read-only tools declared by configuration."""

    def __init__(self, targets: dict[str, TargetDefinition]) -> None:
        if set(targets) != ALLOWED_TOOLS:
            raise ValueError("Gateway registry must contain exactly the approved read-only tools")
        self.targets = targets

    @classmethod
    def load(cls, path: Path | None = None) -> TargetRegistry:
        """Load and validate the checked-in registry."""

        registry_path = path or PROJECT_ROOT / "config" / "gateway-targets.yaml"
        raw = yaml.safe_load(registry_path.read_text(encoding="utf-8"))
        targets = {
            name: TargetDefinition.model_validate(definition)
            for name, definition in raw.get("targets", {}).items()
        }
        return cls(targets)

    def get(self, tool_name: str) -> TargetDefinition:
        """Reject unknown or unregistered tool names."""

        try:
            return self.targets[tool_name]
        except KeyError as exc:
            raise ValueError("Unknown or unregistered tool") from exc
