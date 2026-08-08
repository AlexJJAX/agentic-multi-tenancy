"""Tenant-separated Chroma indexing and doubly scoped retrieval."""

from __future__ import annotations

import hashlib

import chromadb
from chromadb.config import Settings as ChromaSettings
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel, ConfigDict, SecretStr

from app.settings import Settings
from app.shared.claims import AuthorizationError
from app.stores.sqlite import SQLiteStore


class RAGHit(BaseModel):
    """A retrieved chunk whose metadata has passed post-retrieval isolation checks."""

    model_config = ConfigDict(frozen=True)

    content: str
    source: str
    section: str
    chunk_index: int
    tenant_id: str
    score: float


def _sections(markdown: str) -> list[tuple[str, str]]:
    """Split markdown into heading-labelled bodies."""

    current = "Overview"
    body: list[str] = []
    sections: list[tuple[str, str]] = []
    for line in markdown.splitlines():
        if line.startswith("## "):
            if body and "\n".join(body).strip():
                sections.append((current, "\n".join(body).strip()))
            current = line[3:].strip()
            body = []
        else:
            body.append(line)
    if body and "\n".join(body).strip():
        sections.append((current, "\n".join(body).strip()))
    return sections


class TenantRAGService:
    """Own one Chroma collection per active tenant and validate metadata again after search."""

    def __init__(
        self,
        *,
        settings: Settings,
        store: SQLiteStore,
        embeddings: Embeddings | None = None,
    ) -> None:
        self.settings = settings
        self.store = store
        self.embeddings = embeddings or OpenAIEmbeddings(
            model=settings.openai_embedding_model,
            openai_api_key=SecretStr(settings.openai_api_key),
            request_timeout=settings.openai_timeout_seconds,
        )
        self.client = chromadb.EphemeralClient(settings=ChromaSettings(anonymized_telemetry=False))
        self.collections: dict[str, Chroma] = {}

    @staticmethod
    def collection_name(tenant_id: str) -> str:
        """Map an approved tenant identifier to a stable Chroma collection name."""

        return f"kb_{tenant_id.lower().replace('-', '_')}"

    def initialize(self) -> dict[str, int]:
        """Rebuild every checked-in tenant collection from markdown."""

        indexed: dict[str, int] = {}
        splitter = RecursiveCharacterTextSplitter(chunk_size=700, chunk_overlap=80)
        for tenant_id in ("tenant-A", "tenant-B"):
            if self.store.tenant(tenant_id) is None:
                raise AuthorizationError(f"Cannot index inactive tenant {tenant_id}")
            path = self.settings.knowledge_dir / f"{tenant_id}.md"
            source = str(path.relative_to(path.parent.parent))
            documents: list[Document] = []
            ids: list[str] = []
            chunk_index = 0
            for section, body in _sections(path.read_text(encoding="utf-8")):
                for chunk in splitter.split_text(body):
                    digest = hashlib.sha256(chunk.encode()).hexdigest()
                    documents.append(
                        Document(
                            page_content=chunk,
                            metadata={
                                "tenant_id": tenant_id,
                                "source": source,
                                "section": section,
                                "chunk_index": chunk_index,
                                "content_sha256": digest,
                            },
                        )
                    )
                    ids.append(f"{tenant_id}:{digest[:24]}")
                    chunk_index += 1
            name = self.collection_name(tenant_id)
            try:
                self.client.delete_collection(name)
            except chromadb.errors.NotFoundError:
                pass
            collection = Chroma(
                client=self.client,
                collection_name=name,
                embedding_function=self.embeddings,
                collection_metadata={"hnsw:space": "cosine"},
            )
            collection.add_documents(documents, ids=ids)
            self.collections[tenant_id] = collection
            indexed[tenant_id] = len(documents)
        return indexed

    def search(self, *, tenant_id: str, query: str, limit: int | None = None) -> list[RAGHit]:
        """Select one tenant collection, filter metadata, and reject any mismatched result."""

        collection = self.collections.get(tenant_id)
        if collection is None or self.store.tenant(tenant_id) is None:
            raise AuthorizationError("Tenant knowledge collection is unavailable")
        pairs = collection.similarity_search_with_relevance_scores(
            query,
            k=limit or self.settings.retrieval_top_k,
            filter={"tenant_id": tenant_id},
        )
        hits: list[RAGHit] = []
        for document, score in pairs:
            if document.metadata.get("tenant_id") != tenant_id:
                raise AuthorizationError("Cross-tenant retrieval result rejected")
            hits.append(
                RAGHit(
                    content=document.page_content,
                    source=str(document.metadata["source"]),
                    section=str(document.metadata["section"]),
                    chunk_index=int(document.metadata["chunk_index"]),
                    tenant_id=tenant_id,
                    score=float(score),
                )
            )
        return hits

    def ready(self) -> bool:
        """Return whether every seeded tenant has an initialized collection."""

        return set(self.collections) == {"tenant-A", "tenant-B"}
