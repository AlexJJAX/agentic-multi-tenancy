# Source Map

Use this page to choose the smallest useful starting point for a change. The repository has two runtime implementations plus a per-tenant evaluation harness and a configurable orchestration project. The tables below first map `1-Multi-Tenant-Simple/`; later sections map the gateway, evaluation, and orchestration projects. Paths in each section are relative to that implementation. Code projects are organized by layer rather than feature folder.

## Application entry and shared foundations

| Path | Responsibility | Start here when… |
| --- | --- | --- |
| `app/main.py` | FastAPI construction, startup lifespan, router/static/template registration | changing startup, app wiring, root UI delivery, or logging. |
| `app/config.py` | environment-backed settings and project-relative paths | adding/changing non-secret configuration. |
| `app/db.py` | async SQLAlchemy engine, transaction context, schema init, DB health | changing SQLite behavior or transactional access. |
| `app/models.py` | tenant, session, document-tracking, and telemetry schema | evolving persisted application data. |
| `app/schemas.py` | Pydantic request/response/SSE data models | changing public API data shapes. |
| `app/seed.py` | demo tenants, demo user definitions, create-if-missing KB content | changing default demo behavior or seed data. |

## HTTP and application services

| Path | Responsibility |
| --- | --- |
| `app/api/auth.py` | form-based login/token endpoint. |
| `app/api/deps.py` | bearer-JWT parsing, tenant extraction, and admin-role dependency. |
| `app/api/chat.py` | SSE chat route plus session list/detail endpoints; key ownership boundary. |
| `app/api/tenants.py` | public tenant registry reads. |
| `app/api/admin.py` | public health endpoint and admin-only reindex route. |
| `app/services/auth.py` | bcrypt demo-account verification and JWT creation/decoding. |
| `app/services/tenants.py` | tenant registry access/validation. |
| `app/services/chat.py` | session lifecycle and LangChain SQLite message history. |
| `app/services/telemetry.py` | `RagEvent` persistence. |

Keep routes thin and place reusable non-HTTP behavior in the appropriate service. Do not bypass `app/api/deps.py` in a new protected route.

## RAG subsystem

| Path | Responsibility |
| --- | --- |
| `app/rag/ingest.py` | tenant-scoped Markdown discovery, content hashes, header-aware chunking, deterministic IDs. |
| `app/rag/embeddings.py` | configured embedding provider instance. |
| `app/rag/vector_store.py` | ephemeral Chroma client, per-tenant collections, full reindexing, similarity filtering, runtime tenant assertion. |
| `app/rag/chain.py` | retrieval query, prompt assembly, synchronous and streaming RAG orchestration. |
| `app/rag/prompts.py` | grounding/tenant prompt templates and fallback language. |
| `app/rag/citations.py` | safe context and public source formatting. |

Read [RAG and isolation workflow](workflows/rag-and-isolation.md) before modifying any of these files. Isolation is implemented across multiple layers; a change in just one file can undermine the full boundary.

## UI, data, and tests

| Path | Responsibility |
| --- | --- |
| `app/templates/index.html` | UI markup and element contracts. |
| `app/static/app.js` | browser behavior: auth/session/tenant controls, request/SSE handling, source rendering. |
| `app/static/styles.css` | UI styling. |
| `data/kb/tenant-A/payment_returns_policy.md` | sample Acme Payments knowledge base. |
| `data/kb/tenant-B/device_troubleshooting_policy.md` | sample Beta Devices knowledge base. |
| `tests/` | pytest coverage; see [Testing](testing.md). |
| `README.md` | user-facing setup/API overview; verify it against the SSE implementation when updating. |
| `../.github/workflows/openwiki-update.yml` | repository-root scheduled/manual OpenWiki update PR automation. |
| `../AGENTS.md` | repository-root contributor conventions and OpenWiki usage note; its application-layout statements predate the move and should be interpreted relative to `1-Multi-Tenant-Simple/`. |

## MCP gateway implementation (`2-Multi-Tenant-MCP-Tool-Gateway/`)

| Path | Responsibility |
| --- | --- |
| `app/main.py`, `app/lifespan.py`, `app/settings.py` | ASGI wiring, readiness lifecycle, generated local keys/secrets, and settings. |
| `app/auth/` | local identity, JWKS, cookie sessions, and principal resolution. |
| `app/agent/` | tenant RAG, history-aware chat orchestration, and per-request MCP tools. |
| `app/gateway/` | public MCP app, registry, interceptor, routing, and target credential flow. |
| `app/tvm/` | short-lived tenant/tool/request capability validation and exchange. |
| `app/targets/orders/` | orders target and prefix-scoped embedded store access. |
| `app/targets/properties/`, `app/stores/property_store.py` | dual-token properties target and SQLite RLS emulator. |
| `app/audit/` | redacted security and request audit records. |
| `tests/integration/`, `tests/security/`, `tests/unit/` | gateway lifecycle, MCP, isolation, auth, store, and UI coverage. |
| `README.md`, `docs/` | implementation runbook, architecture, security, testing, and workshop context. |

Start with [MCP gateway architecture](architecture/mcp-gateway.md) and [MCP gateway workflow](workflows/mcp-gateway.md) before changing these boundaries.

## Per-tenant evaluation project (`3-Multi-Tenant-Evals/`)

| Path | Responsibility |
| --- | --- |
| `eval_harness/` | corpus loading, tenant validation, retrieval strategies, metric scoring, and report generation. |
| `knowledge/`, `evals/` | tenant-partitioned Markdown corpora and golden JSONL cases. |
| `reports/latest.json` | checked-in evidence trail for the latest deterministic/live evaluation result. |
| `tests/` | deterministic metric, isolation, and regression coverage. |
| `README.md`, `pyproject.toml` | CLI contract, metric definitions, and environment/dependency setup. |

Start here when changing retrieval experiments, per-tenant quality metrics, or evaluation dataset boundaries.

## Tenant-configurable orchestration project (`4-Tenant-Configurable-Orchestration/`)

| Path | Responsibility |
| --- | --- |
| `config/` | Pydantic-validated per-tenant `agent.yaml` persona, tools, guardrails, and approval settings. |
| `orchestration/graph.py` | tenant-specific LangGraph compilation and capability enforcement. |
| `orchestration/` | planning, tools, HITL interrupt/resume, configuration loading, and CLI workflow. |
| `tests/` | compiled-node, forbidden-tool, approval, resume, and config-boundary coverage. |
| `README.md`, `pyproject.toml` | workflow contract, CLI usage, and dependency setup. |

Start here when changing tenant tool capability, graph topology, structured plans, or human approval behavior. The CLI tenant argument is a local identity stand-in, not a production authentication boundary.

## Generated/local artifacts

- `data/demo.sqlite3`, `data/demo.sqlite3-wal`, and `data/demo.sqlite3-shm` are runtime state; do not treat their contents as source-of-truth documentation or commit secrets/data casually.
- `.venv/`, Python/pytest/Ruff caches, and macOS `.DS_Store` files are local artifacts. Ingestion ignores non-Markdown KB files.
- `../openwiki/INSTRUCTIONS.md` is a repository-root, user-authored documentation brief, not generated wiki content. Generated docs start at [quickstart.md](quickstart.md).
- `../.venv/` and repository-root Python/pytest/Ruff caches are workspace artifacts, not part of the implementation directory.

## Practical navigation paths

- **A chat response is wrong:** `app/api/chat.py` → `app/rag/chain.py` → `app/rag/vector_store.py` → `app/rag/ingest.py` / KB Markdown.
- **A user sees auth/tenant behavior:** `app/static/app.js` → `app/api/auth.py` / `app/api/deps.py` → `app/services/auth.py` / `app/seed.py`.
- **A persistence issue occurs:** `app/services/chat.py` or `app/services/telemetry.py` → `app/db.py` → `app/models.py`.
- **A reindex/startup issue occurs:** `app/main.py` → `app/seed.py` → `app/rag/vector_store.py` → `app/api/admin.py`.
