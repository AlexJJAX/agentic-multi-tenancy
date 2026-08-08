"""Deterministic inference doubles shared by pytest and the regression runner."""

from __future__ import annotations

import hashlib
import math
import re

from langchain_core.embeddings import Embeddings

from eval_harness.evaluator import EvaluationDependencies
from eval_harness.models import Chunk, EvalCase

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
CONTEXTUAL_REFERENCES = {"it", "that", "this", "those", "they", "them"}


def _tokens(text: str) -> list[str]:
    return [
        token
        for token in TOKEN_PATTERN.findall(text.casefold())
        if token not in STOPWORDS and len(token) > 1
    ]


class DeterministicEmbeddings(Embeddings):
    """Sparse token-hash vectors that make retrieval repeatable without API calls."""

    dimensions = 2048

    @classmethod
    def _embed(cls, text: str) -> list[float]:
        vector = [0.0] * cls.dimensions
        for token in _tokens(text):
            digest = hashlib.sha256(token.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % cls.dimensions] += 1.0
        magnitude = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / magnitude for value in vector]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        return [self._embed(text) for text in texts]

    def embed_query(self, text: str) -> list[float]:
        return self._embed(text)


class DeterministicQueryRewriter:
    """Resolve contextual references using the previous deterministic experiment."""

    def rewrite(self, question: str, history: tuple[str, ...]) -> str:
        question_tokens = set(TOKEN_PATTERN.findall(question.casefold()))
        if not history or not question_tokens.intersection(CONTEXTUAL_REFERENCES):
            return question
        return f"{' '.join(history[-2:])} {question}"


class ExtractiveAnswerGenerator:
    """Return retrieved evidence verbatim so faithfulness assertions are auditable."""

    def generate(self, _case: EvalCase, hits: list[Chunk]) -> str:
        return hits[0].content if hits else ""


def deterministic_dependencies() -> EvaluationDependencies:
    """Build a fresh set of deterministic inference collaborators."""

    return EvaluationDependencies(
        embeddings=DeterministicEmbeddings(),
        query_rewriter=DeterministicQueryRewriter(),
        answer_generator=ExtractiveAnswerGenerator(),
    )
