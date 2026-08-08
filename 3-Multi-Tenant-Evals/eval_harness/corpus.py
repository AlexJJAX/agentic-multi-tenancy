"""Tenant-boundary-preserving Markdown loading and section-aware chunking."""

from __future__ import annotations

import hashlib
from pathlib import Path

from eval_harness.models import Chunk


def _sections(markdown: str) -> list[tuple[str, str]]:
    heading = "Overview"
    lines: list[str] = []
    sections: list[tuple[str, str]] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if lines and "\n".join(lines).strip():
                sections.append((heading, "\n".join(lines).strip()))
            heading = line[3:].strip()
            lines = []
        elif not line.startswith("# "):
            lines.append(line)
    if lines and "\n".join(lines).strip():
        sections.append((heading, "\n".join(lines).strip()))
    return sections


def load_corpus(knowledge_root: Path) -> dict[str, list[Chunk]]:
    """Load each tenant file into a distinct in-memory collection."""

    collections: dict[str, list[Chunk]] = {}
    for path in sorted(knowledge_root.glob("*.md")):
        tenant_id = path.stem
        chunks: list[Chunk] = []
        for section, content in _sections(path.read_text(encoding="utf-8")):
            digest = hashlib.sha256(f"{tenant_id}:{section}:{content}".encode()).hexdigest()
            chunks.append(
                Chunk(
                    chunk_id=f"{tenant_id}:{digest[:16]}",
                    tenant_id=tenant_id,
                    source=path.name,
                    section=section,
                    content=content,
                )
            )
        collections[tenant_id] = chunks
    return collections
