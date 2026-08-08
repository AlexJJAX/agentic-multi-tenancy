"""Live OpenAI implementations of evaluation inference boundaries."""

from __future__ import annotations

from typing import Any, Protocol

from langchain_core.embeddings import Embeddings
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from pydantic import SecretStr

from eval_harness.models import Chunk, EvalCase
from eval_harness.settings import Settings


def _text_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "\n".join(part for part in parts if part).strip()
    return str(content).strip()


class QueryRewriter(Protocol):
    """Turn a contextual follow-up into a standalone retrieval query."""

    def rewrite(self, question: str, history: tuple[str, ...]) -> str: ...


class AnswerGenerator(Protocol):
    """Generate an answer using only already tenant-scoped evidence."""

    def generate(self, case: EvalCase, hits: list[Chunk]) -> str: ...


class OpenAIQueryRewriter:
    """Live OpenAI contextual query rewriting."""

    def __init__(self, settings: Settings) -> None:
        self.model = ChatOpenAI(
            model=settings.openai_query_rewrite_model,
            api_key=settings.require_openai_api_key(),
            timeout=settings.openai_timeout_seconds,
        )

    def rewrite(self, question: str, history: tuple[str, ...]) -> str:
        history_text = "\n".join(history[-2:]) or "(none)"
        response = self.model.invoke(
            [
                SystemMessage(
                    content=(
                        "Rewrite the latest question as one concise standalone retrieval query. "
                        "Use conversation history only to resolve references. "
                        "Return only the query."
                    )
                ),
                HumanMessage(
                    content=(
                        f"Conversation history:\n{history_text}\n\n"
                        f"Latest question:\n{question}"
                    )
                ),
            ]
        )
        rewritten = _text_content(response.content)
        return rewritten or question


class OpenAIAnswerGenerator:
    """Live OpenAI grounded-answer generator used by normal evaluations."""

    def __init__(self, settings: Settings) -> None:
        self.model = ChatOpenAI(
            model=settings.openai_chat_model,
            api_key=settings.require_openai_api_key(),
            timeout=settings.openai_timeout_seconds,
        )

    def generate(self, case: EvalCase, hits: list[Chunk]) -> str:
        context = "\n\n".join(
            f"SOURCE [{hit.source} — {hit.section}]\n{hit.content}" for hit in hits
        )
        response = self.model.invoke(
            [
                SystemMessage(
                    content=(
                        "Answer only from the supplied tenant-scoped sources. "
                        "If they are insufficient, say so. Do not infer or mention another tenant."
                    )
                ),
                HumanMessage(
                    content=f"Question:\n{case.question}\n\nSources:\n{context or '(none)'}",
                ),
            ]
        )
        return _text_content(response.content)


def create_live_embeddings(settings: Settings) -> Embeddings:
    """Construct the OpenAI embedding client used by the normal CLI."""

    return OpenAIEmbeddings(
        model=settings.openai_embedding_model,
        openai_api_key=SecretStr(settings.require_openai_api_key()),
        request_timeout=settings.openai_timeout_seconds,
    )
