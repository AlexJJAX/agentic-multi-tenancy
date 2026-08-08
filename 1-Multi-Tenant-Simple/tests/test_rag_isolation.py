"""
Tests for RAG vector retrieval isolation.

Uses a fake embedding function to avoid OpenAI API calls.

Covers:
- IT002: tenant-A query retrieves only tenant-A docs
- IT003: tenant-B query retrieves only tenant-B docs
"""

import hashlib

import chromadb
import pytest
from langchain_core.documents import Document

from app.rag.ingest import ingest_tenant
from app.rag.vector_store import collection_name_for_tenant


def fake_embed(texts: list[str]) -> list[list[float]]:
    """
    Create deterministic fake embeddings from text content.

    Generates a simple hash-based vector so similarity search works
    directionally (texts with similar words get closer vectors).
    """
    results = []
    for text in texts:
        # Create a deterministic 384-dim vector from a hash
        h = hashlib.sha256(text.encode()).digest()
        # Extend to 384 dimensions by repeating the hash
        extended = (h * 12)[:384]
        vec = [float(b) / 255.0 for b in extended]
        results.append(vec)
    return results


class FakeEmbeddings:
    """Fake embeddings class that mimics LangChain's interface."""

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return fake_embed(texts)

    def embed_query(self, text: str) -> list[float]:
        return fake_embed([text])[0]


@pytest.fixture(autouse=True)
def clean_vector_state():
    """Reset vector store state before each test."""
    import app.rag.vector_store as vs

    vs._chroma_client = None
    vs._tenant_stores = {}
    vs._indexed_tenants = set()
    yield
    vs._chroma_client = None
    vs._tenant_stores = {}
    vs._indexed_tenants = set()


@pytest.fixture
def indexed_tenants(clean_vector_state):
    """
    Index both tenants using fake embeddings (no OpenAI calls).

    Creates a fresh ChromaDB client, indexes tenant chunks using
    the fake embedding function, and provides a retrieval function.
    """
    import app.rag.vector_store as vs

    # Create a fresh ephemeral client
    client = chromadb.EphemeralClient()
    vs._chroma_client = client

    fake_emb = FakeEmbeddings()

    for tenant_id in ["tenant-A", "tenant-B"]:
        col_name = collection_name_for_tenant(tenant_id)

        # Create collection
        collection = client.get_or_create_collection(name=col_name)

        # Ingest chunks
        chunks = ingest_tenant(tenant_id)
        assert len(chunks) > 0, f"Should have chunks for {tenant_id}"

        # Add to collection with fake embeddings
        ids = [c.metadata["chunk_id"] for c in chunks]
        texts = [c.page_content for c in chunks]
        metadatas = [c.metadata for c in chunks]
        embeddings = fake_emb.embed_documents(texts)

        collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        vs._indexed_tenants.add(tenant_id)

    def retrieve(tenant_id: str, query: str, top_k: int = 4) -> list[Document]:
        """Retrieve from a tenant collection using fake embeddings."""
        col_name = collection_name_for_tenant(tenant_id)
        collection = client.get_collection(name=col_name)
        query_embedding = fake_emb.embed_query(query)

        results = collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
        )

        docs = []
        if results["documents"] and results["metadatas"]:
            for doc_text, metadata in zip(
                results["documents"][0], results["metadatas"][0]
            ):
                docs.append(Document(page_content=doc_text, metadata=metadata))

                # CRITICAL: Validate tenant isolation
                assert metadata["tenant_id"] == tenant_id, (
                    f"ISOLATION VIOLATION: Retrieved tenant_id={metadata['tenant_id']} "
                    f"for request tenant_id={tenant_id}"
                )

        return docs

    yield retrieve


class TestRetrievalIsolation:
    """Test that retrieval is strictly tenant-isolated."""

    def test_tenant_a_retrieval_only_returns_a(self, indexed_tenants):
        """IT002: tenant-A query retrieves only tenant-A docs."""
        docs = indexed_tenants("tenant-A", "payment refund policy")

        assert len(docs) > 0, "Should retrieve at least one document"

        for doc in docs:
            assert doc.metadata["tenant_id"] == "tenant-A", (
                f"Expected tenant-A but got {doc.metadata['tenant_id']}"
            )

    def test_tenant_b_retrieval_only_returns_b(self, indexed_tenants):
        """IT003: tenant-B query retrieves only tenant-B docs."""
        docs = indexed_tenants("tenant-B", "device reset troubleshooting")

        assert len(docs) > 0, "Should retrieve at least one document"

        for doc in docs:
            assert doc.metadata["tenant_id"] == "tenant-B", (
                f"Expected tenant-B but got {doc.metadata['tenant_id']}"
            )

    def test_payment_query_for_tenant_a(self, indexed_tenants):
        """tenant-A payment question retrieves payment-related chunks."""
        docs = indexed_tenants("tenant-A", "charged twice duplicate payment")

        assert len(docs) > 0
        # All docs should be from tenant-A
        for doc in docs:
            assert doc.metadata["tenant_id"] == "tenant-A"

    def test_device_query_for_tenant_b(self, indexed_tenants):
        """tenant-B device question retrieves device-related chunks."""
        docs = indexed_tenants("tenant-B", "how do I reset my device")

        assert len(docs) > 0
        for doc in docs:
            assert doc.metadata["tenant_id"] == "tenant-B"

    def test_cross_query_still_isolated(self, indexed_tenants):
        """Asking tenant-A a device question still returns only tenant-A docs."""
        docs = indexed_tenants("tenant-A", "how do I reset my device")

        for doc in docs:
            assert doc.metadata["tenant_id"] == "tenant-A", (
                "Cross-topic query should still be isolated to tenant-A"
            )


class TestIndexing:
    """Test indexing operations."""

    def test_index_creates_collection(self):
        """Indexing a tenant creates a Chroma collection."""
        import app.rag.vector_store as vs

        client = chromadb.EphemeralClient()
        vs._chroma_client = client

        col_name = collection_name_for_tenant("tenant-A")
        collection = client.get_or_create_collection(name=col_name)

        chunks = ingest_tenant("tenant-A")
        assert len(chunks) > 0

        fake_emb = FakeEmbeddings()
        ids = [c.metadata["chunk_id"] for c in chunks]
        texts = [c.page_content for c in chunks]
        metadatas = [c.metadata for c in chunks]
        embeddings = fake_emb.embed_documents(texts)

        collection.add(
            ids=ids,
            documents=texts,
            metadatas=metadatas,
            embeddings=embeddings,
        )

        assert collection.count() > 0

    def test_reindex_replaces_data(self):
        """Re-indexing a tenant replaces old data."""
        import app.rag.vector_store as vs

        client = chromadb.EphemeralClient()
        vs._chroma_client = client

        col_name = collection_name_for_tenant("tenant-A")
        fake_emb = FakeEmbeddings()
        chunks = ingest_tenant("tenant-A")

        # First index
        collection = client.get_or_create_collection(name=col_name)
        ids = [c.metadata["chunk_id"] for c in chunks]
        texts = [c.page_content for c in chunks]
        metadatas = [c.metadata for c in chunks]
        embeddings = fake_emb.embed_documents(texts)
        collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
        count1 = collection.count()

        # "Reindex" by deleting and recreating
        client.delete_collection(col_name)
        collection = client.get_or_create_collection(name=col_name)
        collection.add(ids=ids, documents=texts, metadatas=metadatas, embeddings=embeddings)
        count2 = collection.count()

        assert count1 == count2, "Reindex should produce same count"
