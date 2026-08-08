# Multi-Tenant RAG Chatbot: Quickstart

This repository is a four-project portfolio that progressively strengthens tenant-aware AI systems:

- [`1-Multi-Tenant-Simple/`](../1-Multi-Tenant-Simple/) is the smaller FastAPI/JWT/SSE RAG demonstration.
- [`2-Multi-Tenant-MCP-Tool-Gateway/`](../2-Multi-Tenant-MCP-Tool-Gateway/) adds cookie sessions, a Streamable HTTP MCP gateway, scoped target credentials, and tenant-isolated RAG.
- [`3-Multi-Tenant-Evals/`](../3-Multi-Tenant-Evals/) measures retrieval quality, answer coverage, faithfulness, and isolation per tenant.
- [`4-Tenant-Configurable-Orchestration/`](../4-Tenant-Configurable-Orchestration/) compiles a tenant-specific LangGraph from YAML capabilities and enforces approval before tools execute.

Projects 1–2 are runtime applications; Projects 3–4 are evaluation and orchestration demonstrations. Their contracts and security boundaries differ. The detailed pages linked below identify which implementation each statement covers. The generated documentation remains at repository root in `openwiki/`.

## Repository layout

```text
./
├── 1-Multi-Tenant-Simple/  # smaller FastAPI/JWT/SSE RAG implementation
│   ├── app/                # API, services, RAG pipeline, and browser UI
│   └── tests/              # pytest suite
├── 2-Multi-Tenant-MCP-Tool-Gateway/  # cookie/MCP/TVM/RAG implementation
│   ├── app/                # identity, chat agent, gateway, targets, stores
│   ├── tests/              # integration, security, unit, and e2e tests
│   ├── docs/               # implementation-specific architecture/security notes
│   └── README.md           # runbook, routes, limitations, and test commands
├── 3-Multi-Tenant-Evals/   # per-tenant retrieval and quality evaluation CLI
│   ├── eval_harness/       # loading, retrieval, scoring, and reporting
│   ├── evals/              # tenant-partitioned golden JSONL cases
│   └── tests/              # deterministic regression checks
├── 4-Tenant-Configurable-Orchestration/  # YAML-driven LangGraph workflow
│   ├── config/             # per-tenant agent capabilities and guardrails
│   ├── orchestration/      # graph compilation, planning, HITL, and tools
│   └── tests/               # graph/capability/interrupt checks
└── openwiki/               # generated repository documentation
```

The central engineering concern is **isolation**: a chat request derives its tenant from a signed JWT, retrieves only from that tenant's collection, validates retrieved metadata again, and rejects reuse of a session owned by another tenant.

## Start here

1. Enter the implementation directory:
   ```bash
   cd 1-Multi-Tenant-Simple
   ```
2. Install the Python dependencies:
   ```bash
   uv sync --all-extras
   ```
3. Create local configuration from the sample file (do not commit `.env`):
   ```bash
   cp .env.example .env
   ```
   Set `OPENAI_API_KEY` and `JWT_SECRET_KEY`; authentication intentionally fails to sign tokens without the latter. See [operations.md](operations.md).
4. Run the application:
   ```bash
   uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```
   Startup creates SQLite tables, seeds missing demo tenants/knowledge-base files, and rebuilds every tenant's in-memory vector collection (`app/main.py`). This requires usable OpenAI credentials for embeddings.
5. Open `http://127.0.0.1:8000` for the demo UI, or log in through `POST /api/auth/token` before calling protected APIs.
6. Run the offline-oriented test suite:
   ```bash
   uv run pytest tests/ -v
   uv run ruff check app tests
   ```

For the MCP gateway implementation, use `cd ../2-Multi-Tenant-MCP-Tool-Gateway`, copy its `.env.example`, set `OPENAI_API_KEY`, and follow [Operations](operations.md) for startup, readiness, reset, and gateway-specific checks. The gateway's deterministic model doubles are available only through explicit test dependency injection. Projects 3 and 4 are independent `uv` projects; their normal CLI paths require `OPENAI_API_KEY`, while tests inject deterministic model doubles. See [Operations](operations.md) for commands.

## Documentation map

- [Architecture overview](architecture/overview.md) — how the four projects differ and where their runtime, evaluation, and orchestration boundaries are.
- [MCP gateway architecture](architecture/mcp-gateway.md) — gateway, TVM, target credentials, stores, and educational substitutes.
- [RAG and isolation workflow](workflows/rag-and-isolation.md) — the simple implementation's startup indexing, streaming chat, citations, and invariants.
- [MCP gateway workflow](workflows/mcp-gateway.md) — cookie-authenticated chat, MCP tool calls, and defense-in-depth tenant enforcement.
- [Operations](operations.md) — configuration and local runbooks for both implementations.
- [Testing](testing.md) — focused test maps and checks for all four projects.
- [Source map](source-map.md) — where to begin in each implementation, evaluation harness, or orchestration layer.

## Product/domain model

Both implementations use **Acme Payments** (`tenant-A`) and **Beta Devices** (`tenant-B`) with deliberately unrelated knowledge. The simple implementation seeds tenant records in `1-Multi-Tenant-Simple/app/seed.py`; the gateway implementation seeds local identity, orders, properties, and knowledge under `2-Multi-Tenant-MCP-Tool-Gateway/`.

The gateway's tenant is derived from the verified identity and is never selected in chat or MCP tool input. Its two public tools are `query_orders` and `query_properties`; orders use a short-lived tenant capability and prefix-scoped store credential, while properties require a gateway service token plus a separately validated user-context JWT. See [MCP gateway architecture](architecture/mcp-gateway.md).

Projects 1, 2, and 4 are development/demo implementations, not complete multi-tenant platforms. Projects 1–2 use local demo identity and process-local Chroma; the gateway additionally uses fakeredis and SQLite RLS emulation, while Project 4 uses an in-memory checkpointer, as educational substitutes. Project 3 evaluates a small checked-in corpus and its deterministic results are not production model-quality claims.

## Important implementation caveats

The following caveats apply to `1-Multi-Tenant-Simple/` only:

- **Session-detail exposure:** `GET /api/sessions/{session_id}` currently has neither JWT authentication nor a tenant-ownership check (`app/api/chat.py`). This conflicts with the repository's isolation goal and should be addressed before exposing the service beyond a controlled demo.
- **Streaming contract:** `POST /api/chat` sends Server-Sent Events (`setup`, `token`, `done`, or `error`), despite declaring `ChatResponse` and despite the README's older JSON response example. Treat the implementation and UI as the current contract.
- **Chroma mode mismatch:** `CHROMA_MODE` is documented/configured, but `app/rag/vector_store.py` always constructs an ephemeral Chroma client. Re-indexing is required after each restart.
- **History only affects prompting:** recent messages are added to the LLM prompt, but retrieval deliberately embeds only the current user message (`app/rag/chain.py`).

For `2-Multi-Tenant-MCP-Tool-Gateway/`, treat embedded identity, fakeredis, SQLite RLS emulation, local generated keys, HTTP/insecure development cookies, and in-memory Chroma as demonstration mechanisms. See [MCP gateway architecture](architecture/mcp-gateway.md) for the target credential and production-boundary caveats.

## Git and documentation status

At this update, `master` has **no commits** and the working tree—including both implementations and `openwiki/`—is untracked. The repository is therefore documented from its current source layout only; there is no version-control history to establish timing or rationale. Future updates should revisit this once commits exist.

## Backlog

- **Security hardening — `1-Multi-Tenant-Simple/app/api/chat.py` session-detail route:** deferred because this update documents current behavior rather than modifying source; add authenticated tenant ownership enforcement and regression coverage.
- **API contract alignment — `1-Multi-Tenant-Simple/README.md`, `app/api/chat.py`, `app/schemas.py`:** deferred because the streaming-vs-JSON mismatch needs a product/client decision before documentation can state one stable public contract.
- **Vector persistence/incremental indexing — `1-Multi-Tenant-Simple/app/config.py`, `app/rag/vector_store.py`, `app/models.py`:** deferred because `CHROMA_MODE` and document hashes imply unfinished operational design; clarify desired persistence and stale-document handling.
- **Relocation history — repository Git state:** deferred because the worktree has no commits; record the intent and source of the `1-Multi-Tenant-Simple/` move in the first commit or project documentation.
