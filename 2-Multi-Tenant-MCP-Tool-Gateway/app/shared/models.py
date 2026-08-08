"""Shared typed models used across trust boundaries."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Principal(BaseModel):
    """A normalized identity produced only after JWT verification."""

    model_config = ConfigDict(frozen=True)

    user_id: str
    username: str
    tenant_id: str
    token: str = Field(repr=False)


class ToolTrace(BaseModel):
    """Secret-free trace information safe for a browser or model."""

    tool: str
    target: str
    request_id: str
    duration_ms: int
    outcome: Literal["allowed", "denied", "error"]


class ToolResult(BaseModel):
    """Internal structured result shared by gateway targets."""

    tool: str
    records: list[dict[str, Any]]
    total_count: int
    count: int
    has_more: bool = False
    trace: ToolTrace


class BrowserIdentity(BaseModel):
    """Public browser-facing identity without bearer credentials."""

    user_id: str
    username: str
    tenant_id: str
    tenant_name: str
