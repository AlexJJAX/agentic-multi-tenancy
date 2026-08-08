# RAG and Tenant-Isolation Workflow

This page is the canonical description of the repository's core product behavior: tenant-specific Markdown is indexed and used to produce grounded, streaming answers without crossing a tenant boundary. The implementation is in `1-Multi-Tenant-Simple/`; source paths below are relative to that directory.

## Knowledge-base ingestion and indexing

### Source boundary

`load_tenant_documents(tenant_id)` recursively reads only `*.md` files under `data/kb/<tenant_id>/`; files outside that tenant directory are never part of that ingestion call (`app/rag/ingest.py`). Each source document gets metadata:

- `tenant_id`
- `source_path`, relative to `data/kb/`
- `filename`
- an 8-hex-character SHA-256 content hash

The chunker first splits at Markdown headings (`#`, `##`, `###`) and then uses a recursive character splitter with a 1,000-character size and 200-character overlap. Chunk IDs are deterministic:

```text
<tenant_id>:<filename>:<content_hash>:<zero-padded chunk index>
```

The corresponding document ID omits the final chunk index. Determinism supports repeatable reindexing and source citations; it also means nested same-named files within one tenant can collide because IDs use `filename`, not `source_path`. Avoid duplicate basenames under a tenant until that behavior changes.

### Index behavior

`index_tenant()` deletes the tenant's existing collection, ingests chunks, adds embeddings/text/metadata, and upserts associated `TenantDocument` rows. A tenant collection is named `kb_<tenant-id-with-hyphens-replaced-by-underscores>`; e.g., `tenant-A` becomes `kb_tenant_A` (`app/rag/vector_store.py`).

The implementation always uses `chromadb.EphemeralClient`, so indexing is a full rebuild and vectors vanish with the process. The admin reindex endpoint follows the same path. The tracked SQLite hashes currently do not drive incremental indexing or deletion cleanup.

## Streaming chat lifecycle

1. The client authenticates at `POST /api/auth/token` and supplies the returned bearer JWT.
2. `POST /api/chat` gets the effective tenant exclusively from `get_current_tenant_id`; `ChatRequest.tenant_id` is accepted for compatibility but ignored.
3. The route validates that the tenant exists. It creates a session when absent; for an existing ID, it rejects a session owned by another tenant. A nonexistent supplied ID is replaced with a new session.
4. Recent messages are loaded from SQLite. They are passed into the LLM prompt but **not** the retrieval embedding query.
5. `stream_rag_chain()` searches the tenant's Chroma collection, yields a `setup` SSE event with citations, then yields `token` events as the OpenAI model streams and a final `done` event with latency.
6. Only after a completed stream does the route save the user/assistant messages, update the session timestamp, and record a successful `RagEvent`. Error paths send an SSE `error` event and write error telemetry, but do not save a partial conversation.

### SSE contract

The implementation emits `text/event-stream` with these event types:

| Event | Data |
| --- | --- |
| `setup` | session ID and formatted source list |
| `token` | one text token/chunk |
| `done` | latency in milliseconds |
| `error` | safe user-facing error message |

Do not build a new client against the README's JSON example without reconciling it with this live protocol (`app/api/chat.py`, `app/static/app.js`).

## Retrieval, grounding, and citations

`build_retrieval_query()` intentionally returns only the current user message: embedding raw history was judged likely to over-weight previous topics (`app/rag/chain.py`). The default is four nearest chunks; `retrieve_for_tenant()` retains hits within an L2-distance delta of 0.25 from the best hit. The prompt includes retrieved context and recent history, specifies the tenant, and directs the model to use only the provided material and return its fixed insufficiency fallback when context cannot answer.

Citations are created by `app/rag/citations.py` and expose chunk ID, tenant, source path, heading, index, and a bounded excerpt. They must never expose embeddings or documents from another tenant.

## Isolation invariants

Defense in depth is deliberate and must be preserved:

1. **Filesystem scope:** ingestion chooses a single `data/kb/<tenant-id>/` subtree.
2. **Physical vector scope:** each tenant receives a distinct Chroma collection.
3. **Metadata scope:** every chunk records its tenant ID.
4. **Runtime retrieval check:** every retrieved document is compared against the request tenant; a mismatch logs a critical event and raises `RuntimeError`.
5. **Citation check:** source formatting independently drops mismatched documents.
6. **Request scope:** chat derives its tenant from a verified JWT rather than a request body.
7. **Session scope:** chat rejects cross-tenant reuse of an existing session ID.

The `RuntimeError` path is treated specially by the route as an isolation error, logged in `rag_events`, and converted into a non-specific SSE error message.

## Known boundary failure

The above invariants apply to the chat/retrieval flow, but **not yet to session-detail reads**: `GET /api/sessions/{session_id}` reads session metadata and messages without a JWT dependency or ownership comparison. This is a real cross-tenant exposure if IDs are discovered. Any security work touching this area should first add JWT/tenant validation and regression tests, then verify the rest of the session API remains usable.

## Safe extension checklist

- New KB formats must retain tenant-scoped discovery, tenant metadata, deterministic IDs, and citation provenance.
- A change to collection layout must keep both tenant separation and the post-retrieval metadata assertion.
- If query rewriting/history-aware retrieval is introduced, test that it improves follow-ups without expanding the tenant search scope.
- Test isolation using fake embeddings, not a live OpenAI key; see [Testing](../testing.md).
- Treat reindex failures, missing OpenAI credentials, and an empty KB as operational cases rather than silently falling back to another tenant's data.
