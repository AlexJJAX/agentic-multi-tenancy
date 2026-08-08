"""
Tests for markdown ingestion pipeline.

Covers:
- T002: Markdown loader loads only tenant-specific files
- T003: Chunk metadata includes tenant ID
- T004: Collection name generation is deterministic
"""

from app.rag.ingest import (
    load_tenant_documents,
    chunk_documents,
    ingest_tenant,
    content_hash,
    extract_first_heading,
)
from app.rag.vector_store import collection_name_for_tenant


class TestContentHash:
    """Tests for content hashing."""

    def test_hash_deterministic(self):
        """Same content always produces the same hash."""
        text = "Hello, world!"
        assert content_hash(text) == content_hash(text)

    def test_hash_different_for_different_content(self):
        """Different content produces different hashes."""
        assert content_hash("foo") != content_hash("bar")

    def test_hash_length(self):
        """Hash is 8 characters long."""
        h = content_hash("test content")
        assert len(h) == 8


class TestExtractHeading:
    """Tests for heading extraction."""

    def test_extracts_h1(self):
        assert extract_first_heading("# Main Title\nSome text") == "Main Title"

    def test_extracts_h2(self):
        assert extract_first_heading("## Section\nSome text") == "Section"

    def test_no_heading(self):
        assert extract_first_heading("Just plain text") is None


class TestLoadTenantDocuments:
    """Tests for tenant document loading."""

    def test_loads_tenant_a_only(self):
        """T002: Loading tenant-A does not return tenant-B paths."""
        docs = load_tenant_documents("tenant-A")

        # Should find at least one document
        assert len(docs) > 0, "tenant-A should have at least one document"

        # Every document should be for tenant-A only
        for doc in docs:
            assert doc.metadata["tenant_id"] == "tenant-A"
            assert "tenant-B" not in doc.metadata["source_path"]

    def test_loads_tenant_b_only(self):
        """Loading tenant-B does not return tenant-A paths."""
        docs = load_tenant_documents("tenant-B")

        assert len(docs) > 0, "tenant-B should have at least one document"

        for doc in docs:
            assert doc.metadata["tenant_id"] == "tenant-B"
            assert "tenant-A" not in doc.metadata["source_path"]

    def test_nonexistent_tenant_returns_empty(self):
        """Non-existent tenant returns empty list."""
        docs = load_tenant_documents("tenant-DOES-NOT-EXIST")
        assert docs == []


class TestChunkDocuments:
    """Tests for document chunking."""

    def test_chunks_have_tenant_metadata(self):
        """T003: Every chunk has tenant_id, source_path, document_id, chunk_index."""
        docs = load_tenant_documents("tenant-A")
        chunks = chunk_documents(docs)

        assert len(chunks) > 0, "Should produce at least one chunk"

        for chunk in chunks:
            assert "tenant_id" in chunk.metadata
            assert chunk.metadata["tenant_id"] == "tenant-A"
            assert "source_path" in chunk.metadata
            assert "document_id" in chunk.metadata
            assert "chunk_index" in chunk.metadata
            assert "chunk_id" in chunk.metadata

    def test_chunk_ids_are_deterministic(self):
        """Same input produces same chunk IDs."""
        docs = load_tenant_documents("tenant-A")

        chunks1 = chunk_documents(docs)
        chunks2 = chunk_documents(docs)

        ids1 = [c.metadata["chunk_id"] for c in chunks1]
        ids2 = [c.metadata["chunk_id"] for c in chunks2]

        assert ids1 == ids2, "Chunk IDs should be deterministic"

    def test_chunk_id_format(self):
        """Chunk IDs follow the format: <tenant_id>:<filename>:<hash>:<index>."""
        docs = load_tenant_documents("tenant-A")
        chunks = chunk_documents(docs)

        for chunk in chunks:
            chunk_id = chunk.metadata["chunk_id"]
            parts = chunk_id.split(":")
            assert len(parts) == 4, f"Chunk ID should have 4 parts: {chunk_id}"
            assert parts[0] == "tenant-A"


class TestCollectionName:
    """Tests for collection name generation."""

    def test_collection_name_deterministic(self):
        """T004: tenant-A maps to the same collection name every time."""
        name1 = collection_name_for_tenant("tenant-A")
        name2 = collection_name_for_tenant("tenant-A")
        assert name1 == name2

    def test_collection_name_format(self):
        """Collection name replaces hyphens with underscores."""
        assert collection_name_for_tenant("tenant-A") == "kb_tenant_A"
        assert collection_name_for_tenant("tenant-B") == "kb_tenant_B"

    def test_different_tenants_different_names(self):
        """Different tenants get different collection names."""
        name_a = collection_name_for_tenant("tenant-A")
        name_b = collection_name_for_tenant("tenant-B")
        assert name_a != name_b


class TestIngestTenant:
    """Tests for the full ingestion pipeline."""

    def test_ingest_produces_chunks(self):
        """Full ingestion pipeline produces chunks with metadata."""
        chunks = ingest_tenant("tenant-A")
        assert len(chunks) > 0

        # Verify all chunks have complete metadata
        for chunk in chunks:
            assert chunk.metadata["tenant_id"] == "tenant-A"
            assert chunk.page_content  # Non-empty content
