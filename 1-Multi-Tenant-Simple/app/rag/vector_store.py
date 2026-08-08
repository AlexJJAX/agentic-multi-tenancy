"""
ChromaDB in-memory vector store management.

Manages tenant-scoped Chroma collections, handles indexing of
document chunks, and provides tenant-isolated retrieval.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

import chromadb
from langchain_chroma import Chroma
from langchain_core.documents import Document

from app.config import settings
from app.db import get_db_session
from app.models import TenantDocument
from app.rag.embeddings import get_embeddings
from app.rag.ingest import ingest_tenant

logger = logging.getLogger(__name__)

# Global ChromaDB client (in-memory by default)
_chroma_client: chromadb.ClientAPI | None = None

# Cache of tenant Chroma vectorstore instances
_tenant_stores: dict[str, Chroma] = {}

# Track which tenants have been indexed
_indexed_tenants: set[str] = set()


def get_chroma_client() -> chromadb.ClientAPI:
    """
    Get or create the ChromaDB client.

    Uses EphemeralClient by default and PersistentClient when explicitly configured.

    Returns:
        ChromaDB client instance.
    """
    global _chroma_client

    if _chroma_client is None:
        if settings.chroma_mode == "persistent":
            settings.chroma_persist_path_resolved.mkdir(parents=True, exist_ok=True)
            _chroma_client = chromadb.PersistentClient(
                path=str(settings.chroma_persist_path_resolved)
            )
            logger.info(
                "Initialized ChromaDB PersistentClient at %s",
                settings.chroma_persist_path_resolved,
            )
        else:
            try:
                _chroma_client = chromadb.EphemeralClient()
                logger.info("Initialized ChromaDB EphemeralClient (in-memory)")
            except AttributeError:
                # Fallback for older ChromaDB versions
                _chroma_client = chromadb.Client()
                logger.info("Initialized ChromaDB Client (fallback)")

    return _chroma_client


def collection_name_for_tenant(tenant_id: str) -> str:
    """
    Generate a deterministic Chroma collection name for a tenant.

    Replaces characters that are invalid in Chroma collection names.

    Args:
        tenant_id: The tenant identifier.

    Returns:
        Safe collection name string (e.g., "kb_tenant_A").
    """
    return "kb_" + tenant_id.replace("-", "_")


def get_tenant_vectorstore(tenant_id: str) -> Chroma:
    """
    Get or create a Chroma vectorstore for a specific tenant.

    Each tenant gets its own collection for isolation.

    Args:
        tenant_id: The tenant identifier.

    Returns:
        LangChain Chroma vectorstore instance scoped to the tenant.
    """
    if tenant_id not in _tenant_stores:
        collection_name = collection_name_for_tenant(tenant_id)
        client = get_chroma_client()

        _tenant_stores[tenant_id] = Chroma(
            client=client,
            collection_name=collection_name,
            embedding_function=get_embeddings(),
        )
        logger.info(
            "Created vectorstore for tenant %s (collection: %s)",
            tenant_id,
            collection_name,
        )

    return _tenant_stores[tenant_id]


async def index_tenant(tenant_id: str) -> dict:
    """
    Index (or reindex) all markdown documents for a single tenant.

    Clears the existing collection, re-ingests markdown files,
    embeds chunks, and stores them in ChromaDB. Also updates
    the tenant_documents table in SQLite.

    Args:
        tenant_id: The tenant to index.

    Returns:
        Dict with 'tenant_id', 'documents', and 'chunks' counts.
    """
    collection_name = collection_name_for_tenant(tenant_id)
    client = get_chroma_client()

    # Delete existing collection if it exists, then recreate
    try:
        client.delete_collection(collection_name)
        logger.info("Deleted existing collection: %s", collection_name)
    except Exception:
        pass  # Collection didn't exist yet

    # Remove cached store so it gets recreated
    _tenant_stores.pop(tenant_id, None)

    # Ingest and chunk the tenant's markdown files
    chunks = ingest_tenant(tenant_id)

    if not chunks:
        logger.warning("No chunks to index for tenant: %s", tenant_id)
        _indexed_tenants.discard(tenant_id)
        return {"tenant_id": tenant_id, "documents": 0, "chunks": 0}

    # Get the vectorstore (creates new collection)
    vectorstore = get_tenant_vectorstore(tenant_id)

    # Prepare chunk IDs, texts, and metadatas for ChromaDB
    chunk_ids = [c.metadata["chunk_id"] for c in chunks]
    texts = [c.page_content for c in chunks]
    metadatas = [c.metadata for c in chunks]

    # Add documents to Chroma with deterministic IDs
    vectorstore.add_texts(
        texts=texts,
        metadatas=metadatas,
        ids=chunk_ids,
    )

    # Count unique source documents
    doc_ids = set(c.metadata["document_id"] for c in chunks)

    # Update tenant_documents table in SQLite
    async with get_db_session() as session:
        for doc_id in doc_ids:
            # Find chunks for this document
            doc_chunks = [c for c in chunks if c.metadata["document_id"] == doc_id]
            first_chunk = doc_chunks[0]

            tenant_doc = TenantDocument(
                document_id=doc_id,
                tenant_id=tenant_id,
                source_path=first_chunk.metadata["source_path"],
                content_hash=first_chunk.metadata["content_hash"],
                chunk_count=len(doc_chunks),
                indexed_at=datetime.now(timezone.utc).isoformat(),
                status="indexed",
            )

            # Merge to handle re-indexing (upsert)
            await session.merge(tenant_doc)

    _indexed_tenants.add(tenant_id)

    logger.info(
        "Indexed tenant %s: %d documents, %d chunks",
        tenant_id,
        len(doc_ids),
        len(chunks),
    )

    return {
        "tenant_id": tenant_id,
        "documents": len(doc_ids),
        "chunks": len(chunks),
    }


async def index_all_tenants(tenant_ids: list[str]) -> list[dict]:
    """
    Index all provided tenants.

    Args:
        tenant_ids: List of tenant IDs to index.

    Returns:
        List of index result dicts.
    """
    results = []
    for tenant_id in tenant_ids:
        result = await index_tenant(tenant_id)
        results.append(result)
    return results


def get_indexed_tenants() -> list[str]:
    """Get the list of currently indexed tenant IDs."""
    return sorted(_indexed_tenants)


def retrieve_for_tenant(
    tenant_id: str,
    query: str,
    top_k: Optional[int] = None,
) -> list[Document]:
    """
    Retrieve the most relevant chunks from a tenant's collection.

    Performs similarity search and validates that all results
    belong to the specified tenant (isolation check).

    Args:
        tenant_id: The tenant to search within.
        query: The search query text.
        top_k: Number of results to return (defaults to config value).

    Returns:
        List of retrieved Document objects with metadata.

    Raises:
        RuntimeError: If cross-tenant documents are detected.
    """
    if top_k is None:
        top_k = settings.retrieval_top_k

    vectorstore = get_tenant_vectorstore(tenant_id)

    # Perform similarity search with score
    docs_with_scores = vectorstore.similarity_search_with_score(query, k=top_k)

    docs = []
    if docs_with_scores:
        # The results are sorted by score (lowest distance first)
        best_score = docs_with_scores[0][1]
        
        # Filter out docs that are significantly less relevant than the best match
        # For Chroma's default L2 distance, lower is better.
        SCORE_THRESHOLD_DELTA = 0.25
        
        for doc, score in docs_with_scores:
            if score <= best_score + SCORE_THRESHOLD_DELTA:
                docs.append(doc)
            else:
                logger.info(
                    "Filtered out doc '%s' due to low relevance (score: %.4f, best: %.4f)", 
                    doc.metadata.get("heading", "unknown"), 
                    score, 
                    best_score
                )
    for doc in docs:
        doc_tenant = doc.metadata.get("tenant_id")
        if doc_tenant != tenant_id:
            logger.critical(
                "TENANT ISOLATION VIOLATION: Retrieved doc with tenant_id=%s "
                "for request tenant_id=%s. Chunk: %s",
                doc_tenant,
                tenant_id,
                doc.metadata.get("chunk_id", "unknown"),
            )
            raise RuntimeError(
                "Cross-tenant retrieval detected. This is an isolation error."
            )

    logger.info(
        "Retrieved %d chunks for tenant %s (query: %.50s...)",
        len(docs),
        tenant_id,
        query,
    )
    return docs
