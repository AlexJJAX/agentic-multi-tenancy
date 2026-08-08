# Testing and evaluation strategy

## Test philosophy

Tests construct isolated temporary SQLite and key paths and pass `RuntimeDependencies` with
deterministic embeddings and response logic. They never read a developer `.env` or call
OpenAI. Normal application startup has no offline setting; a missing live credential fails
before initialization.

Any auth, ingestion, retrieval, gateway, target, TVM, or store regression requires both a
successful same-tenant case and a cross-tenant denial. Testing only the happy path would prove
functionality, not isolation.

## Layers

| Layer | What it proves |
| --- | --- |
| Unit | Claim normalization, signatures, audiences, capabilities, registry redaction |
| Store/service | Redis prefix checks, SQLite authorizer, disposable tenant context |
| Gateway integration | Header stripping, routing, target-specific credentials, MCP schemas |
| Application integration | Cookie behavior, history ownership, RAG scope, chat and SSE |
| Concurrency | Tenant context cannot leak between simultaneous property/gateway calls |
| Evaluation | Stable multi-record synthesis still produces the ten expected answers |

The tests deliberately invoke internal services directly *and* through public HTTP/MCP
boundaries. Direct tests pinpoint policy failures; boundary tests catch middleware and
serialization mistakes.

## Run the gates

```bash
uv sync --all-extras
uv run pytest tests/ -v --cov=app --cov-report=term-missing
uv run ruff check app tests scripts
uv run mypy app
uv run python scripts/run_evals.py
```

No test should require `OPENAI_API_KEY`. The evaluation runner boots the complete ASGI
lifespan with injected doubles, logs in as Tenant A, and traverses chat, gateway, target, store,
history, and audit components. It uses exact match because the doubles have stable compact outputs. A
live model evaluation should use repeated trials and semantic/judge metrics as a separate
report.

## High-value isolation cases

- Tenant A retrieval returns no Tenant B chunk, even for a device-themed query.
- Tenant B cannot open Tenant A session history by guessing a session ID.
- Alice/Carol and Bob/Jake cannot list or open each other's conversation histories despite
  sharing the same tenant data scope.
- Tenant B cannot delete Tenant A history, and a successful owner deletion removes both the
  session and its messages.
- Client-supplied tenant headers are removed before principal propagation.
- A capability for `query_orders` cannot authorize another tool or request ID.
- An orders credential cannot read a key outside its signed prefix.
- A user JWT cannot replace the service credential at the properties target.
- Direct `properties` table reads fail after the tenant view is configured.
- Concurrent Tenant A/B calls retain the correct connection-local view.
- SSE output contains only Tenant A records and safe trace metadata.

## What is not measured yet

The injected-double suite does not measure OpenAI answer variance, token cost, live latency, embedding
drift, long-context degradation, or managed-service behavior. Project 3 adds per-tenant
retrieval/faithfulness metrics and an ablation notebook. A production test plan would also run
load tests, chaos tests, issuer/key rotation scenarios, real Redis ACL integration, PostgreSQL
RLS integration, and browser-level accessibility checks.
