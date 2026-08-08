# Testing Guidance

This page covers both implementations. The first sections describe `1-Multi-Tenant-Simple/`; the gateway section describes `2-Multi-Tenant-MCP-Tool-Gateway/`. Test paths are relative to the implementation named by the section.

## Baseline checks

Run checks from `1-Multi-Tenant-Simple/`:

```bash
cd 1-Multi-Tenant-Simple
uv run pytest tests/ -v
uv run ruff check app tests
```

The tests are designed to avoid live OpenAI calls. In particular, RAG-isolation tests construct deterministic fake embeddings and isolated ephemeral Chroma clients. Keep new tests independent of `OPENAI_API_KEY` and external services.

## Test map

| Area | Tests | What they establish |
| --- | --- | --- |
| Ingestion/chunk identity | `tests/test_ingest.py` | tenant-scoped Markdown discovery, missing-KB handling, chunk metadata/IDs, and collection naming. |
| Retrieval isolation | `tests/test_rag_isolation.py` | tenant-A and tenant-B searches return only the requested tenant's documents, including cross-topic queries. |
| Chat/source contract | `tests/test_chat_api.py` | request validation and source formatting, including suppression of cross-tenant sources. |
| JWT/auth/admin | `tests/test_jwt_auth.py` | valid/invalid/expired token behavior, tenant claims, protected chat access, and admin authorization. |
| Tenant services | `tests/test_tenants.py` | idempotent tenant seed behavior and unknown-tenant rejection. |
| UI/API shape | `tests/test_ui_contract.py` | root UI elements, tenant-list shape, auth-before-body behavior, and static assets. |

Most HTTP tests mock the FastAPI lifespan so database initialization and startup indexing do not run. This keeps API contract tests fast but means they do not validate the complete live startup path.

## Change-oriented test selection

| If changing… | Start with… | Also consider… |
| --- | --- | --- |
| KB discovery, chunking, IDs, or collection naming | `tests/test_ingest.py` | `tests/test_rag_isolation.py` |
| Chroma retrieval/filtering/index behavior | `tests/test_rag_isolation.py` | a new direct test of `retrieve_for_tenant()` with fake embeddings |
| JWT claims, login, protected routes, or roles | `tests/test_jwt_auth.py` | `tests/test_ui_contract.py` if browser flows change |
| Chat request, stream events, sources, or session behavior | `tests/test_chat_api.py` | `tests/test_ui_contract.py`; add SSE parsing/ownership coverage where relevant |
| Templates/static JS/CSS | `tests/test_ui_contract.py` | manual browser check against the running service |
| Startup/seeding/schema operations | focused tenant tests | add a lifespan integration test that avoids live OpenAI services |

## Isolation regression standard

Any change that touches authentication, sessions, ingestion, retrieval, citations, or tenant metadata must demonstrate that tenant-A content cannot be obtained in tenant-B context (and vice versa). Test both the intended access path and malformed/cross-tenant input where the route exposes identifiers.

The current suite proves collection-level isolation via a custom retrieval helper, not every production guard in `retrieve_for_tenant()`. It also does not cover the unauthenticated session-detail route. Prioritize tests for that route when closing the documented exposure.

## Useful patterns in the existing suite

- `FakeEmbeddings` in `tests/test_rag_isolation.py` gives deterministic vectors without API calls.
- Route tests use `httpx.ASGITransport` and patch `app.main.lifespan` to bypass startup mutation/external embedding work.
- Tests reset module-level Chroma globals before and after each retrieval test; retain similar isolation if code continues to use global stores.

## Project 3 evaluation checks

From `3-Multi-Tenant-Evals/`, run:

```bash
uv sync --all-extras
uv run pytest -v --cov=eval_harness --cov-report=term-missing
uv run ruff check eval_harness tests
uv run python tests/run_regression.py --output /tmp/per-tenant-evals.json
```

The harness loads tenant-partitioned golden JSONL cases, compares raw-query and contextual-rewrite retrieval, and scores recall, answer coverage, faithfulness, and isolation separately per tenant. The loader and scorer recheck tenant directory/row agreement and returned chunk ownership. Keep tests deterministic and do not interpret the small-corpus report as production model quality.

## Project 4 orchestration checks

From `4-Tenant-Configurable-Orchestration/`, run:

```bash
uv sync --all-extras
uv run pytest -v --cov=orchestration --cov-report=term-missing
uv run ruff check orchestration tests
uv run mypy orchestration
```

Tests inspect each tenant's compiled graph, prove forbidden tools are absent or rejected before approval, verify LangGraph interrupt approval/rejection on the same thread, and check configuration/directory tenant mismatches. When changing graph construction or configuration validation, preserve the invariant that unauthorized tools are not registered for that tenant.

## Gateway checks and coverage

From `2-Multi-Tenant-MCP-Tool-Gateway/`, run:

```bash
uv sync --all-extras
uv run pytest tests/ -v
uv run ruff check app tests
uv run mypy app
```

The injected-double suite covers MCP initialization and schemas, JWT signature/audience checks, spoofed-header removal, cookie/logout and session isolation, capability expiry/tampering/request binding, cross-tenant order denial, dual-token properties authorization, SQLite direct-table denial, disposable tenant context, concurrent principals, RAG/history isolation, lifecycle idempotency, and audit redaction. Use the focused directories under `tests/integration/`, `tests/security/`, and `tests/unit/` when changing those boundaries.

Run Ruff after Python changes even when only documentation-related test files are touched. Before a production-oriented change, add coverage for error paths (missing configuration, empty KBs, embedding failures, and cross-tenant identifiers) rather than relying on manual UI testing.
