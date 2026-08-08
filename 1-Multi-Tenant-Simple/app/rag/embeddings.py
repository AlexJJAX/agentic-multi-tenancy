"""
Embeddings wrapper module.

Provides a singleton OpenAI embeddings instance.
"""

import logging

from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings

from app.config import settings

logger = logging.getLogger(__name__)

# Singleton embeddings instance — reused across the application
# to ensure consistent embedding model for both indexing and retrieval
_embeddings_instance: Embeddings | None = None


def get_embeddings() -> Embeddings:
    """
    Get the shared OpenAI embeddings instance.

    Uses text-embedding-3-small by default, configurable via
    EMBEDDING_MODEL environment variable.

    Returns:
        Configured OpenAIEmbeddings instance.
    """
    global _embeddings_instance

    if _embeddings_instance is None:
        _embeddings_instance = OpenAIEmbeddings(
            model=settings.embedding_model,
            openai_api_key=settings.require_openai_api_key(),
        )
        logger.info("Initialized embeddings with model: %s", settings.embedding_model)

    return _embeddings_instance
