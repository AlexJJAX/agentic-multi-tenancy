"""Embedding-based retrieval over an already selected tenant collection."""

from __future__ import annotations

import math
import re

from langchain_core.embeddings import Embeddings

from eval_harness.models import Chunk

TOKEN_PATTERN = re.compile(r"[a-z0-9]+")
STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "does",
    "for",
    "from",
    "how",
    "i",
    "in",
    "is",
    "it",
    "my",
    "of",
    "on",
    "or",
    "the",
    "this",
    "to",
    "what",
    "when",
    "with",
}


def tokens(text: str) -> list[str]:
    """Normalize text into content-bearing tokens."""

    return [
        token
        for token in TOKEN_PATTERN.findall(text.casefold())
        if token not in STOPWORDS and len(token) > 1
    ]


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    numerator = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(value**2 for value in left))
    right_norm = math.sqrt(sum(value**2 for value in right))
    return numerator / (left_norm * right_norm) if left_norm and right_norm else 0.0


def retrieve(
    collection: list[Chunk],
    query: str,
    *,
    top_k: int,
    embeddings: Embeddings,
) -> list[Chunk]:
    """Rank only the already-selected tenant collection."""

    documents = [f"{chunk.section} {chunk.content}" for chunk in collection]
    document_vectors = embeddings.embed_documents(documents)
    query_vector = embeddings.embed_query(query)
    if any(len(vector) != len(query_vector) for vector in document_vectors):
        raise ValueError("Embedding dimensions must match for query and corpus vectors")
    ranked = sorted(
        zip(collection, document_vectors, strict=True),
        key=lambda item: (_cosine_similarity(query_vector, item[1]), item[0].chunk_id),
        reverse=True,
    )
    return [chunk for chunk, _vector in ranked[:top_k]]
