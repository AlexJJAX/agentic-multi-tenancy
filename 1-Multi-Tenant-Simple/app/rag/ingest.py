"""
Markdown document ingestion pipeline.

Handles loading markdown files from tenant KB directories, splitting
them into chunks with deterministic IDs, and computing content hashes
for change detection.
"""

import hashlib
import logging
from typing import Optional

from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter

from app.config import settings

logger = logging.getLogger(__name__)


def content_hash(text: str) -> str:
    """
    Compute a short SHA-256 hash of the given text.

    Args:
        text: The text content to hash.

    Returns:
        First 8 characters of the hex digest.
    """
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def extract_first_heading(text: str) -> Optional[str]:
    """
    Extract the first markdown heading from the text.

    Args:
        text: Markdown text content.

    Returns:
        The heading text without the '#' prefix, or None if no heading found.
    """
    for line in text.split("\n"):
        stripped = line.strip()
        if stripped.startswith("#"):
            # Remove leading '#' characters and whitespace
            return stripped.lstrip("#").strip()
    return None


def load_tenant_documents(tenant_id: str) -> list[Document]:
    """
    Load all markdown files from a tenant's KB directory.

    Recursively discovers .md files under data/kb/<tenant_id>/
    and creates LangChain Document objects with tenant metadata.

    Args:
        tenant_id: The tenant identifier whose KB to load.

    Returns:
        List of Document objects with content and metadata.
    """
    tenant_dir = settings.kb_root_path / tenant_id

    if not tenant_dir.exists():
        logger.warning("KB directory does not exist for tenant: %s", tenant_id)
        return []

    documents = []
    for md_file in sorted(tenant_dir.rglob("*.md")):
        content = md_file.read_text(encoding="utf-8")
        # Relative path from KB root for metadata
        relative_path = md_file.relative_to(settings.kb_root_path)

        doc = Document(
            page_content=content,
            metadata={
                "tenant_id": tenant_id,
                "source_path": str(relative_path),
                "filename": md_file.name,
                "content_hash": content_hash(content),
            },
        )
        documents.append(doc)
        logger.info("Loaded document: %s (tenant: %s)", relative_path, tenant_id)

    logger.info(
        "Loaded %d document(s) for tenant %s", len(documents), tenant_id
    )
    return documents


def chunk_documents(
    documents: list[Document],
    chunk_size: int = 1000,
    chunk_overlap: int = 200,
) -> list[Document]:
    """
    Split documents into chunks with enriched metadata.

    Each chunk receives a deterministic chunk ID based on tenant ID,
    source path, content hash, and chunk index.

    Args:
        documents: List of loaded documents to split.
        chunk_size: Maximum characters per chunk (default: 1000).
        chunk_overlap: Character overlap between chunks (default: 200).

    Returns:
        List of chunked Document objects with full metadata.
    """
    from langchain_text_splitters import MarkdownHeaderTextSplitter
    
    headers_to_split_on = [
        ("#", "h1"),
        ("##", "h2"),
        ("###", "h3"),
    ]
    md_splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=headers_to_split_on, 
        strip_headers=False
    )
    
    char_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        separators=["\n\n", "\n", " ", ""],
    )

    all_chunks = []

    for doc in documents:
        # First split by markdown headers
        md_splits = md_splitter.split_text(doc.page_content)
        
        # Then chunk the header sections
        splits = char_splitter.split_documents(md_splits)

        for i, chunk in enumerate(splits):
            tenant_id = doc.metadata["tenant_id"]
            filename = doc.metadata["filename"]
            doc_hash = doc.metadata["content_hash"]
            source_path = doc.metadata["source_path"]

            # Deterministic chunk ID: <tenant_id>:<filename>:<doc_hash>:<chunk_index>
            chunk_id = f"{tenant_id}:{filename}:{doc_hash}:{i:04d}"

            # Extract heading from markdown metadata or fallback
            heading = chunk.metadata.get("h3") or chunk.metadata.get("h2") or chunk.metadata.get("h1")
            if not heading:
                heading = extract_first_heading(chunk.page_content)

            # Create a new document with original metadata + new chunk metadata
            new_metadata = {
                "tenant_id": tenant_id,
                "source_path": source_path,
                "filename": filename,
                "content_hash": doc_hash,
                "chunk_id": chunk_id,
                "chunk_index": i,
                "heading": heading,
                "document_id": f"{tenant_id}:{filename}:{doc_hash}",
            }
            chunk.metadata = new_metadata

            all_chunks.append(chunk)

    logger.info(
        "Created %d chunk(s) from %d document(s)",
        len(all_chunks),
        len(documents),
    )
    return all_chunks


def ingest_tenant(tenant_id: str) -> list[Document]:
    """
    Full ingestion pipeline for a single tenant.

    Loads markdown files, splits into chunks, and returns
    enriched Document objects ready for embedding and indexing.

    Args:
        tenant_id: The tenant to ingest.

    Returns:
        List of chunked Document objects.
    """
    documents = load_tenant_documents(tenant_id)
    if not documents:
        logger.warning("No documents found for tenant: %s", tenant_id)
        return []

    chunks = chunk_documents(documents)
    return chunks
