"""Correlation identifier validation and generation."""

from __future__ import annotations

from uuid import UUID, uuid4


def correlation_id(candidate: str | None = None) -> str:
    """Return a canonical UUID, replacing malformed client input."""

    if candidate:
        try:
            return str(UUID(candidate))
        except ValueError:
            pass
    return str(uuid4())
