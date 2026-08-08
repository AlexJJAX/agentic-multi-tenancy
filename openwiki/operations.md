# Operations and Local Runbook

This page covers both implementations. The first section applies to `1-Multi-Tenant-Simple/`; the gateway runbook applies to `2-Multi-Tenant-MCP-Tool-Gateway/`. Source paths such as `app/config.py` are relative to the implementation named by the section.

## Configuration

Use `1-Multi-Tenant-Simple/.env.example` as the non-secret configuration reference, then keep values in an untracked `1-Multi-Tenant-Simple/.env`. `app/config.py` loads `.env` with `override=True`, so local file values take precedence. Do not put credentials or secrets in documentation, source, or generated database files.

`JWT_SECRET_KEY` is required by `app/config.py` and token signing, but it is absent from the supplied `.env.example`; add it to the local `.env` without committing the value.

| Setting | Default / purpose | Notes |
| --- | --- | --- |
| `OPENAI_API_KEY` | empty | Needed for live embeddings and chat. Startup indexing invokes embeddings. |
| `JWT_SECRET_KEY` | empty | Required to mint access tokens; signing raises an error when absent. |
| `CHAT_MODEL` | `gpt-5-mini` | Used by `ChatOpenAI` with temperature 0.1. |
| `EMBEDDING_MODEL` | `text-embedding-3-small` | Used for Chroma indexing/retrieval. |
| `SQLITE_PATH` | `data/demo.sqlite3` | Relative paths resolve from the project root. |
| `KB_ROOT` | `data/kb` | Source Markdown root, partitioned by tenant ID. |
| `RETRIEVAL_TOP_K` | `4` | Maximum candidate chunks before relevance filtering. |
| `CHAT_HISTORY_MAX_MESSAGES` | `8` | Recent messages supplied to the prompt. |
| `CHROMA_MODE` | `in-memory` | Reported in logs/health, but does not currently select a persistent backend. |
| LangSmith settings | tracing defaults enabled | Optional tracing configuration; keep API keys only in `.env`/CI secrets. |

`APP_HOST` and `APP_PORT` are configuration values and are logged at startup; the standard local command can specify the same bind parameters explicitly.

## Common commands

Run application commands from the relocated implementation directory:

```bash
cd 1-Multi-Tenant-Simple

# Install runtime and development dependencies
uv sync --all-extras

# Start the local service and UI
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# Run the application suite and static checks
uv run pytest tests/ -v
uv run ruff check app tests
```

The project requires Python 3.13 or later (`1-Multi-Tenant-Simple/pyproject.toml`). The checked-in `1-Multi-Tenant-Simple/data/demo.sqlite3` and its WAL/SHM companions are local generated artifacts; the application can create the SQLite schema itself during startup.

## Startup, health, and reindexing

Startup is intentionally stateful: it initializes the database, seeds absent demo records/files, and indexes all registered tenants. This means a restart may call external embedding APIs and incur corresponding latency/cost. Seed content is **create-if-missing**, so it will not overwrite a locally edited KB file (`app/seed.py`).

`GET /api/health` is public and reports SQLite reachability, tenant count, indexed tenant IDs, configured model names, and the configured Chroma mode. It does not prove an OpenAI key is usable or that every vector collection is healthy beyond the process-local indexed-tenant tracker.

`POST /api/admin/reindex` requires a JWT whose role is `admin`. With a `tenant_id`, it rebuilds that tenant's collection; without one it rebuilds all registered tenant collections. The route does not validate a supplied ID before indexing: an unknown ID resolves to an empty result. Use an existing tenant ID and consult the response counts.

Because Chroma is ephemeral, reindexing must be repeated automatically at each application start. Do not rely on `TenantDocument` records as proof that an index survives a restart.

## Operational and security watchpoints

- Set a strong local `JWT_SECRET_KEY`; do not depend on defaults, because no default is provided.
- Demo users are intentionally defined in source (`app/seed.py`) and are not an identity-management solution. Replace the user store before any non-demo deployment.
- SQLite `rag_events` records raw user messages and error strings; message history is also retained. There is no deletion/retention API. Establish a data policy before using real customer data.
- The session-detail endpoint is currently unauthenticated. Restrict or fix it before deploying outside a trusted environment; details are in [RAG and isolation workflow](workflows/rag-and-isolation.md).
- `POST /api/chat` is SSE in the code, not the JSON response illustrated by the README. Operational clients/proxies need streaming support.
- The broad admin reindex scope is role-based rather than tenant-bound. Confirm this is the intended admin model.

## Gateway runbook (`2-Multi-Tenant-MCP-Tool-Gateway/`)

```bash
cd 2-Multi-Tenant-MCP-Tool-Gateway
cp .env.example .env
uv sync --all-extras
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Set `OPENAI_API_KEY` for startup; the runtime always constructs live OpenAI embeddings/chat components. Deterministic behavior is available only through explicit test dependency injection. The lifespan creates ignored `.local/` keys/secrets, applies idempotent migrations and seeds, initializes embedded stores, and rebuilds both ephemeral Chroma indexes. `/health` is liveness; `/ready` succeeds only after all keys, stores, indexes, and MCP applications are initialized. `uv run python -m app.cli reset` removes only `.local/`; the next start regenerates it.

The gateway is localhost-only demo infrastructure: use HTTPS, secure cookies, production OIDC, rate limiting, and CSRF protection before deployment. Fakeredis and SQLite RLS emulation are not Redis ACLs or PostgreSQL RLS, and the raw user JWT passed to the properties target should become token exchange or an actor token in production. If MCP returns 401, use a user token with the `mcp-gateway` audience; target 401/403 responses usually indicate a purpose-bound credential mismatch.

## Evaluation and orchestration projects

Projects 3 and 4 are separate `uv` projects and normally use live OpenAI models. Keep credentials in each project's untracked `.env`; tests use injected deterministic doubles.

```bash
cd 3-Multi-Tenant-Evals
uv sync --all-extras
cp .env.example .env
uv run tenant-evals
uv run pytest -v
uv run ruff check eval_harness tests
uv run python tests/run_regression.py

cd ../4-Tenant-Configurable-Orchestration
uv sync --all-extras
cp .env.example .env
uv run pytest -v
uv run ruff check orchestration tests
uv run mypy orchestration
uv run tenant-workflow --tenant tenant-A --query "Show order A-1001" --approve
```

Project 3 writes its live evidence trail to `reports/latest.json`; its checked-in deterministic result is an analytical regression over the small corpus. Project 4's `--tenant` flag is only a local CLI stand-in for verified identity and must not become user-controlled HTTP input. Its normal workflow uses LangGraph's in-memory checkpointer and has no offline runtime mode.

The root `.github/workflows/ci.yml` runs four independent jobs. Projects 1–3 run pytest/Ruff (with coverage for all), Project 2 also runs mypy and gateway evals, Project 3 runs its regression script, and Project 4 runs mypy. CI uses no OpenAI secret.

## Documentation automation

`.github/workflows/openwiki-update.yml` schedules an OpenWiki refresh daily at 08:00 UTC and supports manual dispatch. It installs the OpenWiki CLI, runs `openwiki code --update --print`, and uses a pull-request action to submit changes covering `openwiki`, the agent instruction files, and the workflow. It does not run either application's tests, Ruff, or mypy. Its provider/tracing credentials are referenced as GitHub secrets; only secret names, never values, belong in repository documentation.

There is currently no source git history or remote. When the first commits are created, update this wiki with the history that explains architectural decisions and operational changes.
