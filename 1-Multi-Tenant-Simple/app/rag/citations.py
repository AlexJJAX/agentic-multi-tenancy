"""
Source citation formatting utilities.

Converts retrieved LangChain Documents into the source metadata
format expected by the API response, with excerpts and validation.
"""

import logging
from typing import Optional

from langchain_core.documents import Document

from app.schemas import SourceInfo

logger = logging.getLogger(__name__)

# Maximum excerpt length in characters
MAX_EXCERPT_LENGTH = 200


def format_source(doc: Document, tenant_id: str) -> Optional[SourceInfo]:
    """
    Format a retrieved document chunk into a source citation.

    Validates that the document belongs to the specified tenant
    before creating the source info object.

    Args:
        doc: The retrieved LangChain Document.
        tenant_id: The expected tenant ID for validation.

    Returns:
        SourceInfo object, or None if validation fails.
    """
    metadata = doc.metadata

    # Validate tenant isolation
    doc_tenant = metadata.get("tenant_id")
    if doc_tenant != tenant_id:
        logger.critical(
            "Source formatting blocked cross-tenant document: "
            "expected=%s, found=%s, chunk=%s",
            tenant_id,
            doc_tenant,
            metadata.get("chunk_id", "unknown"),
        )
        return None

    # Create excerpt from the chunk content
    excerpt = doc.page_content[:MAX_EXCERPT_LENGTH]
    if len(doc.page_content) > MAX_EXCERPT_LENGTH:
        excerpt += "..."

    return SourceInfo(
        source_id=metadata.get("chunk_id", "unknown"),
        tenant_id=tenant_id,
        source_path=metadata.get("source_path", "unknown"),
        heading=metadata.get("heading"),
        chunk_index=metadata.get("chunk_index", 0),
        excerpt=excerpt,
    )


def format_sources(docs: list[Document], tenant_id: str) -> list[SourceInfo]:
    """
    Format multiple retrieved documents into source citations.

    Filters out any documents that fail tenant validation.

    Args:
        docs: List of retrieved LangChain Documents.
        tenant_id: The expected tenant ID for validation.

    Returns:
        List of validated SourceInfo objects.
    """
    sources = []
    for doc in docs:
        source = format_source(doc, tenant_id)
        if source is not None:
            sources.append(source)
    return sources


def format_context_for_prompt(docs: list[Document]) -> str:
    """
    Format retrieved documents into a context string for the LLM prompt.

    Each chunk is labeled with its source and heading for traceability.

    Args:
        docs: List of retrieved Document chunks.

    Returns:
        Formatted context string.
    """
    if not docs:
        return "(No relevant context found in tenant documents.)"

    parts = []
    for i, doc in enumerate(docs, 1):
        heading = doc.metadata.get("heading", "No heading")
        source = doc.metadata.get("source_path", "unknown")
        parts.append(
            f"[Source {i}: {source} — {heading}]\n{doc.page_content}"
        )

    return "\n\n---\n\n".join(parts)
