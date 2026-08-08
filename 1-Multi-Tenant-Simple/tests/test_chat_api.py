"""
Tests for chat API endpoint contract.

Covers:
- T006: Empty message is rejected
- T007: Source formatting excludes embeddings
- API request/response contract validation
"""

import pytest

from app.schemas import ChatRequest, SourceInfo, ChatResponse
from app.rag.citations import format_source, format_sources
from langchain_core.documents import Document


class TestChatRequestValidation:
    """Test chat request validation."""

    def test_valid_request(self):
        """Valid request creates a ChatRequest."""
        req = ChatRequest(
            tenant_id="tenant-A",
            session_id=None,
            message="What is your refund policy?",
        )
        assert req.tenant_id == "tenant-A"
        assert req.message == "What is your refund policy?"

    def test_empty_message_rejected(self):
        """T006: Empty message is rejected with validation error."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ChatRequest(
                tenant_id="tenant-A",
                session_id=None,
                message="",  # Empty - should fail min_length=1
            )

    def test_message_too_long_rejected(self):
        """Message exceeding max_length is rejected."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ChatRequest(
                tenant_id="tenant-A",
                session_id=None,
                message="x" * 4001,  # Exceeds max_length=4000
            )

    def test_tenant_id_is_now_optional(self):
        """
        tenant_id is now optional in ChatRequest.
        The backend derives it from the JWT, not the body.
        This test verifies the schema accepts a request without tenant_id.
        """
        req = ChatRequest(
            session_id=None,
            message="Hello",
            # tenant_id intentionally omitted
        )
        assert req.tenant_id is None
        assert req.message == "Hello"


class TestSourceFormatting:
    """Test source citation formatting."""

    def test_format_source_with_metadata(self):
        """T007: Source formatting includes metadata but not embeddings."""
        doc = Document(
            page_content="Test content about payments",
            metadata={
                "tenant_id": "tenant-A",
                "chunk_id": "tenant-A:test.md:abc123:0000",
                "source_path": "tenant-A/test.md",
                "heading": "Test Heading",
                "chunk_index": 0,
            },
        )

        source = format_source(doc, "tenant-A")

        assert source is not None
        assert source.source_id == "tenant-A:test.md:abc123:0000"
        assert source.tenant_id == "tenant-A"
        assert source.source_path == "tenant-A/test.md"
        assert source.heading == "Test Heading"
        assert source.chunk_index == 0
        assert "Test content" in source.excerpt

    def test_format_source_no_embeddings(self):
        """Source objects never contain raw embeddings."""
        doc = Document(
            page_content="Test content",
            metadata={
                "tenant_id": "tenant-A",
                "chunk_id": "test:0000",
                "source_path": "test.md",
                "chunk_index": 0,
            },
        )

        source = format_source(doc, "tenant-A")
        assert source is not None

        # Convert to dict and verify no embedding-related fields
        source_dict = source.model_dump()
        assert "embedding" not in source_dict
        assert "vector" not in source_dict

    def test_cross_tenant_source_blocked(self):
        """Source formatting blocks cross-tenant documents."""
        doc = Document(
            page_content="Secret tenant-B data",
            metadata={
                "tenant_id": "tenant-B",
                "chunk_id": "tenant-B:secret.md:xyz:0000",
                "source_path": "tenant-B/secret.md",
                "chunk_index": 0,
            },
        )

        # Trying to format as tenant-A should return None
        source = format_source(doc, "tenant-A")
        assert source is None, "Cross-tenant source should be blocked"

    def test_format_sources_filters_cross_tenant(self):
        """format_sources filters out any cross-tenant documents."""
        docs = [
            Document(
                page_content="Valid tenant-A content",
                metadata={
                    "tenant_id": "tenant-A",
                    "chunk_id": "tenant-A:doc.md:abc:0000",
                    "source_path": "tenant-A/doc.md",
                    "chunk_index": 0,
                },
            ),
            Document(
                page_content="Invalid tenant-B content",
                metadata={
                    "tenant_id": "tenant-B",
                    "chunk_id": "tenant-B:secret.md:xyz:0000",
                    "source_path": "tenant-B/secret.md",
                    "chunk_index": 0,
                },
            ),
        ]

        sources = format_sources(docs, "tenant-A")
        assert len(sources) == 1
        assert sources[0].tenant_id == "tenant-A"

    def test_excerpt_truncation(self):
        """Long content is truncated in the excerpt."""
        long_content = "A" * 300
        doc = Document(
            page_content=long_content,
            metadata={
                "tenant_id": "tenant-A",
                "chunk_id": "test:0000",
                "source_path": "test.md",
                "chunk_index": 0,
            },
        )

        source = format_source(doc, "tenant-A")
        assert source is not None
        assert len(source.excerpt) < len(long_content)
        assert source.excerpt.endswith("...")


class TestChatResponse:
    """Test chat response schema."""

    def test_response_schema(self):
        """Response contains expected fields."""
        response = ChatResponse(
            tenant_id="tenant-A",
            session_id="session_abc123",
            answer="This is the answer.",
            sources=[
                SourceInfo(
                    source_id="tenant-A:doc.md:abc:0000",
                    tenant_id="tenant-A",
                    source_path="tenant-A/doc.md",
                    heading="Test",
                    chunk_index=0,
                    excerpt="Excerpt...",
                )
            ],
        )

        assert response.tenant_id == "tenant-A"
        assert response.session_id == "session_abc123"
        assert len(response.sources) == 1
