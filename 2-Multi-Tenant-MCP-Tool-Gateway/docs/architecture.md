# Architecture decisions

## Scope and system boundary

`app.main:app` is the only listening application. FastAPI owns the UI, JSON APIs, local
identity routes, internal HTTP targets, health endpoints, and lifecycle. Two official-SDK
`FastMCP` Streamable HTTP ASGI applications are mounted at `/mcp` and
`/internal/mcp/properties`; their session managers are entered by the top-level lifespan.

Keeping one process makes the project reproducible on a laptop while retaining explicit
interfaces between components. The target boundaries use real HTTP/MCP-shaped contracts,
audience-bound tokens, and independent validators. They are deployment seams, even though this
demo hosts them together.

## Request path

1. The browser exchanges a demo password for an opaque, HttpOnly session cookie.
2. `/api/chat` reloads a verified principal; the request schema has no tenant field.
3. History is loaded by the tuple `(tenant_id, user_id, session_id)`.
4. RAG selects exactly one Chroma collection, applies a metadata filter, and validates every
   result again.
5. The live OpenAI backend creates a fresh `MultiServerMCPClient` containing the user's bearer
   token outside model messages. Automated tests inject a backend double at application
   construction and route through the same gateway services deterministically.
6. Gateway middleware verifies the user token, strips client-supplied context headers, and
   binds normalized identity to an async context variable.
7. The registry chooses one approved target. The selected target validates its own credential
   contract and asks its store to enforce tenant scope.
8. The agent persists the exchange only after successful completion and records secret-free
   correlation metadata.

The SSE `/api/chat/stream` route emits safe phase names and answer chunks. It never emits JWTs,
capabilities, internal headers, prompts, or target credentials.

## Why two target authorization patterns?

Orders demonstrate token vending. The gateway supplies its service token plus a maximum
60-second, tenant/tool/request-bound capability. The orders target verifies both, then uses its
own service token to ask TVM for an even shorter prefix credential. The embedded Redis adapter
checks that prefix before every `GET` and `MGET`.

Properties demonstrate service authorization plus separately verified user context. The target
requires a gateway service token as primary authorization and validates a user JWT for the
properties-context audience. A fresh SQLite connection creates a temporary tenant table,
queries a protected view, and denies base-table reads through the authorizer.

Using two patterns makes the trade-off visible: delegated store credentials minimize ambient
authority, while service-plus-user context better resembles systems where row-level policy
needs actor claims. Neither pattern treats a forwarded header as proof.

## RAG and agent choices

One Chroma collection per tenant is simpler to reason about than one global collection with a
filter. A filter and post-retrieval check still run as defense in depth. The trade-off is more
collection lifecycle work at high tenant counts; a production service might use a shared index
with mandatory server-side partitioning, or allocate dedicated indexes to high-risk tenants.

The agent uses live OpenAI tool calling because Project 2 focuses on gateway trust
boundaries. Project 4 adds explicit LangGraph planning and approval without crowding this
project's security lesson. Deterministic collaborators exist only as explicitly injected test
doubles: normal startup has no offline switch and fails without an OpenAI key.

## Lifecycle and failure behavior

Startup generates or loads local RSA keys, applies idempotent migrations and seeds, initializes
stores, rebuilds both tenant indexes, constructs mounted MCP apps, and marks readiness only when
every check passes. Failure is closed: the service never reports ready with a missing collection
or store.

Per-request timeouts bound internal HTTP and model calls. Authentication or authorization
exceptions become non-revealing messages at public boundaries. Audit writes intentionally omit
prompt/response content; a telemetry failure must not broaden access.

## Production replacements

| Demo component | Production boundary |
| --- | --- |
| Embedded users and generated keys | Managed OIDC provider, rotated keys, short browser session |
| One-process mounts | Independently deployed gateway, targets, and policy service |
| Fakeredis | Redis Cluster with TLS, ACL users, and externally verified prefix policy |
| SQLite protected view | PostgreSQL RLS with transaction-local tenant context |
| In-memory Chroma | Durable vector service with tenant partition lifecycle |
| Process memory token cache | Encrypted, bounded cache with issuer revocation strategy |
| SSE after full agent completion | Native agent event streaming with cancellation/backpressure |

The target architecture would also add rate limits, CSRF protection, secure cookies, structured
distributed traces, encrypted secrets, network policy, key rotation, and disaster recovery.
