# Architecture Overview

## Scope

The repository contains four related but independently runnable projects. `1-Multi-Tenant-Simple/` is the FastAPI/JWT/SSE RAG application described below; `2-Multi-Tenant-MCP-Tool-Gateway/` adds cookie sessions, a public Streamable HTTP MCP gateway, target services, TVM, and tenant-isolated RAG; `3-Multi-Tenant-Evals/` measures per-tenant retrieval and answer quality; and `4-Tenant-Configurable-Orchestration/` compiles tenant-specific LangGraph topologies from YAML. Projects 3–4 extend the architecture story without sharing runtime state with Projects 1–2.

## Shape of the simple application

The simple application is a single FastAPI process with a browser UI. `1-Multi-Tenant-Simple/app/main.py` creates the app, mounts `/static`, renders `app/templates/index.html` at `/`, and registers tenant, auth, chat, and admin routers. It uses a lifespan hook rather than a separate worker: startup initializes local state and performs indexing before the service is ready.

```text
Browser (Jinja + vanilla JS) / API client
                |
          FastAPI routes
                |
  auth dependencies + application services
        |                     |
 SQLite registry/session/      RAG orchestration
 telemetry persistence              |
                       tenant-specific Chroma collection
                                |
                          OpenAI embeddings + chat model
```

### Startup lifecycle

`app.main.lifespan` performs the following ordered work:

1. creates the KB directory if absent;
2. calls `init_db()` to enable SQLite WAL/foreign keys and create ORM tables;
3. runs idempotent seed routines for demo tenants and missing KB Markdown files;
4. lists registered tenants and calls `index_all_tenants()`.

Indexing is process-local and rebuilds collections, so startup availability depends on the configured embedding model/API credentials. See [RAG and isolation workflow](../workflows/rag-and-isolation.md).

## Storage and state boundaries

| Store                          | What it contains                                                         | Lifecycle                                                 | Source                                  |
| ------------------------------ | ------------------------------------------------------------------------ | --------------------------------------------------------- | --------------------------------------- |
| SQLite                         | tenant registry, session metadata, indexed-document metadata, RAG events | file-backed at `SQLITE_PATH`; default `data/demo.sqlite3` | `app/models.py`, `app/db.py`            |
| LangChain SQLite message store | human/AI messages for each session                                       | same SQLite file, accessed through the synchronous URL    | `app/services/chat.py`, `app/config.py` |
| Chroma                         | embedded Markdown chunks and metadata, one collection per tenant         | ephemeral/in-memory; rebuilt at startup/reindex           | `app/rag/vector_store.py`               |
| KB filesystem                  | source Markdown under `data/kb/<tenant-id>/`                             | source content; missing demo files are created once       | `app/rag/ingest.py`, `app/seed.py`      |

`Tenant`, `ChatSession`, `TenantDocument`, and `RagEvent` are the application-owned ORM models. `TenantDocument` records content hashes/chunk counts, but current indexing clears and reconstructs a collection rather than using these records for incremental updates.

## API surface

| Endpoint                                           | Protection           | Current behavior                                                                      |
| -------------------------------------------------- | -------------------- | ------------------------------------------------------------------------------------- |
| `GET /`                                            | public               | Render the Jinja-based local UI.                                                      |
| `GET /api/tenants`, `GET /api/tenants/{tenant_id}` | public               | List/look up tenant registry records.                                                 |
| `POST /api/auth/token`                             | public               | OAuth2-form login for an in-memory demo account; returns a bearer JWT and tenant ID.  |
| `POST /api/chat`                                   | bearer JWT           | Starts an SSE stream. Tenant is taken from the token, not the body.                   |
| `GET /api/sessions`                                | bearer JWT           | List sessions for the token's tenant.                                                 |
| `GET /api/sessions/{session_id}`                   | **currently public** | Return session metadata and up to 100 messages; lacks tenant verification.            |
| `GET /api/health`                                  | public               | Report DB status, registered/indexed tenant counts, and configured model/mode labels. |
| `POST /api/admin/reindex`                          | admin JWT            | Reindex one supplied tenant ID or every registered tenant.                            |

Routes are intentionally thin: `app/api/` owns HTTP validation/dependencies, `app/services/` owns tenant/session/auth/telemetry behavior, and `app/rag/` owns ingestion, retrieval, prompting, and citation formatting. Refer to [Source map](../source-map.md) when changing a surface.

## Authentication and authorization

`app/services/auth.py` builds an in-memory user store from `DEMO_USERS` in `app/seed.py`, bcrypt-hashing the demo passwords at import time. There is no user table or external identity provider. A JWT contains `sub`, `tenant_id`, `role`, and `exp`; `JWT_SECRET_KEY` must be configured to mint tokens. `get_current_tenant_id` decodes the bearer token and feeds the tenant claim into protected routes. `require_admin` checks only the `role` claim.

This makes the design suitable for local demos while defining the intended authorization boundary: request payload fields do not choose the tenant. The admin token is seeded as tenant-A-scoped but may request a reindex for another tenant; clarify whether that cross-tenant operational authority is intentional before building production authorization.

## UI integration

The UI lives in `app/templates/index.html`, `app/static/app.js`, and `app/static/styles.css`. It is served by the same process, allowing it to exercise tenant selection, login, session handling, reindex controls, SSE token rendering, and source display without a separate frontend build pipeline. Tests in `tests/test_ui_contract.py` check key element IDs and static asset availability rather than browser-level behavior.

## Change guidance

- Add or alter an HTTP contract in `app/api/`, its Pydantic models in `app/schemas.py`, and the corresponding UI/tests together.
- Treat SQLite and Chroma as separate consistency domains. A successful relational write does not imply a persistent vector index, and reindexing only recreates vectors from KB files.
- Preserve the JWT-derived tenant flow and do not introduce request-controlled tenant selection into chat/retrieval paths.
- When adding a protected session/data route, use the dependency pattern from `app/api/deps.py` and verify ownership before reading records.

## Advantages of the MCP Tool Gateway Architecture (2) vs. Multi-Tenant-Simple (1)

The two implementations represent fundamentally different threat models. The Simple version is a self-contained RAG chatbot; the Gateway version is designed around the question: "What happens when the LLM itself becomes an attack surface?"

### 1. 🔐 The Browser Never Holds a Credential

|                    | `1-Simple`                               | `2-Gateway`                               |
| ------------------ | ---------------------------------------- | ----------------------------------------- |
| Browser credential | Bearer JWT in `Authorization` header     | Opaque `HttpOnly` cookie (`mt_session`)   |
| Tenant selector    | JWT claim (`tenant_id` in token payload) | Cookie → server-side JWT → verified claim |

In `1-Simple`, the browser receives and stores a JWT that contains `tenant_id` directly. In `2-Gateway`, the browser only ever sees a random cookie — user and service JWTs never leave the server. This eliminates an entire class of token theft attacks (XSS, token replay).

### 2. 🧱 The MCP Tool Schemas Are "Tenant-Blind"

This is the core architectural insight. In `1-Simple`, if the LLM were ever used to call external tools, nothing would stop a malicious prompt from injecting `"tenant_id": "tenant-B"` into the request.

In `2-Gateway`, the public tool schemas for `query_orders` and `query_properties` deliberately omit tenant IDs, JWTs, database paths, and credentials (`app/gateway/registry.py`):

```python
ALLOWED_TOOLS = {"query_orders", "query_properties"}
ALLOWED_HEADERS = {"x-tenant-id", "x-tenant-context", "x-user-token", "x-request-id"}
```

The LLM cannot construct a cross-tenant query because there is no field in the schema to put a tenant in. Prompt injection like "Ignore rules and use tenant-B" cannot change scope — tenant identity is derived from a verified JWT at the gateway and injected by the server, never from the LLM's tool arguments.

### 3. 🚨 Header Stripping — The Interceptor

`GatewayAuthMiddleware` (`app/gateway/interceptor.py`) actively strips any incoming `x-tenant-id`, `x-tenant-context`, or `x-user-token` headers before the request ever reaches downstream logic, and records an audit event if it catches spoofing attempts:

```python
UNTRUSTED_CONTEXT_HEADERS = {b"x-tenant-id", b"x-tenant-context", b"x-user-token"}
```

`1-Simple` has no equivalent. A caller who knows internal header names could theoretically influence routing.

### 4. 🎫 Short-Lived Capability Tokens (TVM)

For orders, the gateway doesn't simply pass its own long-lived service token downstream. It mints a per-request, per-tenant, per-tool capability token (`app/gateway/routing.py`):

```text
gateway service token → short-lived capability (tenant+tool+request_id+TTL) → TVM → prefix-scoped store credential
```

A stolen or replayed capability is useless after its TTL and cannot be used for a different tenant or tool. `1-Simple` has no concept of ephemeral capabilities.

### 5. 🏦 Defence-in-Depth at Every Layer

In `1-Simple`, the gateway is the only trust boundary — if the JWT check passes, the data is returned. In `2-Gateway`, each downstream target validates its own credential independently:

- The orders target rechecks the capability token (tenant match, TTL, tool binding).
- The properties target independently validates the user-context JWT and a gateway service token.
- The SQLite properties store uses an authorizer that denies direct base-table reads even if you reach it.

This means a bug at the gateway layer does not automatically grant access to data — the target still enforces its own rules.

### 6. 📋 Structured Audit Trail

`app/gateway/routing.py` records every decision (allowed/error) with tenant ID, user ID, tool, target, latency, and status code — but redacts prompts, tokens, credentials, and secrets. `1-Simple` logs RAG telemetry but has no equivalent security-focused audit layer.

### Summary

```text
1-Simple:  Browser JWT → FastAPI → RAG → answer
           (one trust boundary, tenant from JWT claim)

2-Gateway: Browser cookie → chat API → per-request MCP client
               → /mcp gateway (strips headers, verifies JWT)
                   → capability mint → target (re-validates)
                       → prefix-scoped or RLS-filtered store
           (multiple independent trust boundaries, tenant never in LLM tool input)
```

The key trade-off: `1-Simple` is far easier to understand and operate. `2-Gateway` is the right architecture when the LLM is a potential attack vector — its tool input schemas form the security boundary, not just the auth layer.

# Simplified End-to-end flow

1. **Startup phase** (managed by `lifespan.py`)

   The STARTUP phase (managed by lifespan.py) happens before the server starts accepting any network traffic.

   Because this application is built on FastAPI, it uses an "ASGI lifespan". The entire STARTUP sequence must successfully complete—keys generated, database migrated, dummy data seeded, and RAG collections fully loaded into memory—before Uvicorn opens port 8000 to the outside world.

   If you try to load `http://127.0.0.1:8000` in your browser while the STARTUP phase is still running (for example, while it is creating the RAG embeddings), the browser will just spin and wait because the UI login screen simply isn't being served yet.

   Once STARTUP finishes and the S6[`/ready → true`] gate is passed, the HTTP server opens the port, and then the user can reach the login screen.

   ```mermaid

   sequenceDiagram
         autonumber
         participant Terminal
         actor Browser
         participant Uvicorn as Uvicorn (Port 8000)
         participant Lifespan as lifespan.py (ASGI Startup)
         participant Crypto as RSA Key Management
         participant DB as SQLite Store
         participant RAG as Chroma / Embeddings

         Note over Terminal: Command executed: <br> "uv run uvicorn app.main:app --host 127.0.0.1 --port 8000 --env-file ../.en"

         activate Lifespan
         Terminal->>Lifespan:
         Lifespan->>Crypto: ensure_rsa_keypair() (Identity & Gateway)
         Lifespan->>DB: migrate() (Create tables/WAL)
         Lifespan->>DB: seed() (Insert dummy tenants & demo users)

         Lifespan->>RAG: initialize()
         Note over RAG: Reads local KB Markdown files<br/>Requests OpenAI Embeddings
         RAG-->>Lifespan: Loads tenant-specific collections into memory

         Lifespan->>Lifespan: Evaluate readiness
         Note right of Lifespan: Checks DB health and verifies<br/>tenant chunks are indexed.

         Lifespan-->>Uvicorn: ASGI Startup Complete
         deactivate Lifespan

         Note over Uvicorn: Port 8000 OPENS

         Uvicorn-->>Browser: 200 OK (Renders UI Login Screen)
         Note over Browser: The user is presented <br> with a UI comprising an account selector

   ```

   The below Mermaid sequence diagram shows the high-level flow of the STARTUP phase, from user exceuting the terminal command to the web browser rendering the login screen.

   ![Startup phase](./screenshots/Startup_phase.png)

2. **User login**

   The user is presented with a UI comprising an account selector. This selector is purely a convenience mechanism to populate the `username` field with a seeded demo account (e.g., `alice@tenant-a.demo`).

   Upon submission, only the `username` and `password` are sent to the `/auth/login` endpoint. The server verifies the credentials and looks up the user's assigned tenant in the database.

   The server then securely issues a JWT containing the `tenant_id` and sets an opaque `mt_session` cookie in the browser. The frontend itself never selects, stores, or transmits a `tenant_id`, guaranteeing strictly server-enforced tenant isolation.

   ```mermaid
   sequenceDiagram
         autonumber
         actor User
         participant Browser
         participant Uvicorn as Uvicorn (FastAPI)
         participant Auth as Identity Service
         participant DB as SQLite Store

         User->>Browser: Select account <br>(e.g., alice@tenant-a.demo) & Submit
         Note over Browser: Populates username & password only.<br/>Tenant ID is NOT sent.
         Browser->>Uvicorn: POST /auth/login {username, password}

         activate Uvicorn
         Uvicorn->>Auth: Verify credentials
         activate Auth
         Auth->>DB: Lookup user profile
         DB-->>Auth: Returns user data (includes tenant_id)
         Auth-->>Uvicorn: Valid identity (tenant_id determined)
         deactivate Auth

         Uvicorn->>Uvicorn: Mint internal JWT embedding tenant_id claim
         Uvicorn->>DB: Store JWT in browser_sessions table

         Uvicorn-->>Browser: 200 OK + Set-Cookie: mt_session (opaque session ID)
         deactivate Uvicorn

         Note over Browser, Uvicorn: The browser never sees or transmits the tenant_id.<br/>Tenant isolation is now strictly enforced server-side.
   ```

   The below sequence diagram depicts the UI Account Selection flow:

   ![Account Selection](./screenshots/UI_Account_selection.png)

3. **Chat request processing** (`POST /api/chat`)

   When the user sends a message, the browser simply includes the `mt_session` cookie. It does not send any tenant identifiers in the request body.

   The server intercepts this cookie and looks it up in the `browser_sessions` table to retrieve the underlying user JWT. It cryptographically verifies the JWT, ensuring the session is valid and determining the `tenant_id` for the current request.

   Using this server-enforced `tenant_id`, the system loads only the relevant tenant's chat history from SQLite, and queries only the relevant tenant's Chroma vector store for RAG context. A post-retrieval check ensures no cross-tenant knowledge leaked.

   Finally, the prompt (along with the tenant's RAG context and history) is sent to the LLM. If the LLM decides it needs real-time structured data, it generates a tool call for `query_orders` or `query_properties`.

   ```mermaid
   sequenceDiagram
   autonumber
   participant Browser UI
   participant API as Chat API (/api/chat)
   participant Auth as Session Layer
   participant Store as SQLite (History)
   participant RAG as ChromaDB (RAG)
   participant LLM as OpenAI LLM


   Browser UI->>API: POST /api/chat (prompt, mt_session cookie)
   Note over Browser UI: User <br> Type message & clicks Send

   activate API
   Note over API, Auth: Intercept cookie and lookup browser_sessions
   API->>Auth: Cryptographically verify JWT
   Auth-->>API: Returns valid identity (tenant_id)

   par Load History
         API->>Store: Fetch chat history where tenant = tenant_id
         Store-->>API: Returns session history
   and Retrieve Knowledge
         API->>RAG: Query Chroma collection matching tenant_id
         RAG-->>API: Returns embedded context chunks
   end

   API->>API: Post-retrieval validation (assert no cross-tenant knowledge leaked)

   API->>LLM: Send context (System instructions, tool schemas, RAG context, history, user prompt)
   activate LLM

   alt Needs real-time structured data
         LLM-->>API: Returns JSON Tool Call (e.g., query_orders)
   else Can answer with static knowledge
         LLM-->>API: Returns natural language response
   end
   deactivate LLM

   API-->>Browser UI: Stream response / execution state via SSE
   deactivate API
   ```

   The below sequence diagram depicts the "Chat request processing" flow:

   ![Chat request processing](./screenshots/Chat_request_processing.png)

4. **MCP Public Gateway** (`/mcp`)

   **How the LLM decides to use a tool:** When the Chat API sends a prompt to the LLM, it includes the system instructions and the schemas of all available tools (e.g., `query_orders`, `query_properties`). The LLM evaluates the user's request against its provided static RAG context and history. If the request requires real-time or structured data that it doesn't currently hold (like checking the live status of an order or searching property listings), the LLM autonomously recognizes that the intent matches a tool's description and generates a structured JSON tool call instead of a text response.

   When the LLM generates a tool call, the internal Chat Service creates a per-request MCP client and forwards the call to the `/mcp` gateway, attaching the user's JWT.

   The `GatewayAuthMiddleware` (the interceptor) sits at the edge of this gateway. It first verifies the JWT (ensuring it has the `mcp-gateway` audience). Crucially, it then inspects the incoming HTTP request for spoofed internal security headers (such as `x-tenant-id`, `x-tenant-context`, or `x-user-token`). If any are found, it actively strips them and logs a `strip_untrusted_context` audit event.

   Once verified and cleaned, the principal (containing the `tenant_id`, `user_id`, and `request_id`) is safely bound to a secure context variable for the duration of the request.

   The gateway then evaluates the tool call. Because the exposed tool schemas (e.g., `query_orders`, `query_properties`) are intentionally "tenant-blind" (they do not accept a tenant parameter), the LLM cannot maliciously specify a different tenant. The routing layer dispatches the request to the appropriate internal target.

   ```mermaid
   sequenceDiagram
   autonumber
   participant LLM as OpenAI LLM
   participant Chat as Chat Service
   participant Client as MCP Client
   participant Interceptor as GatewayAuthMiddleware
   participant Audit as Audit Logger
   participant Gateway as MCP Gateway Router
   participant Target as Internal Targets

   LLM->>Chat: Generates structured JSON tool call
   activate Chat
   Chat->>Client: Create per-request MCP client

   Client->>Interceptor: POST /mcp (attaches user JWT)
   activate Interceptor

   Interceptor->>Interceptor: Cryptographically verify JWT<br/>(audience: mcp-gateway)

   opt Contains spoofed headers? (e.g., x-tenant-id)
         Interceptor->>Interceptor: STRIP untrusted headers
         Interceptor->>Audit: Log 'strip_untrusted_context'
   end

   Interceptor->>Interceptor: Bind Principal to secure ContextVar<br/>(tenant_id, user_id, request_id)

   Interceptor->>Gateway: Forward cleaned request
   deactivate Interceptor
   activate Gateway

   Note over Gateway: Schemas are "tenant-blind".<br/>Tenant identity is guaranteed by the ContextVar.
   Gateway->>Gateway: Evaluate tool call & route

   Gateway->>Target: Dispatch request
   activate Target
   Target-->>Gateway: Return structured JSON result
   deactivate Target

   Gateway-->>Client: Return result
   deactivate Gateway

   Client-->>Chat: Return result
   deactivate Chat
   ```

   The below sequence diagram depicts the "MCP public gateway" flow. Specifically, it illustrates how the interceptor actively cleans incoming requests, verifies the JWT, and safely binds the principal before dispatching to the tenant-blind routing layer.

   ![MCP Public Gateway](./screenshots/MCP_Public_Gateway.png)

5. **Orders Target Path** (`query_orders`)

   If the gateway routes the request to the orders service, it does not simply pass the user's long-lived JWT. Instead, it uses the Token Vending Machine (TVM) service to mint a highly restricted, short-lived (e.g., 5 minute) capability token. This token explicitly binds the `tenant_id` to the `query_orders` tool.

   The gateway forwards the request to the internal Orders service, passing this capability token via the `x-tvm-capability` header.

   The Orders service middleware intercepts the request and cryptographically validates the TVM capability token (checking the signature, TTL expiration, and ensuring the bound tenant matches the requested data scope).

   Once authorized, the Orders handler reads from a prefix-scoped file specific to that tenant (e.g., `data/orders/{tenant-id}.json`) and returns the data back up the chain to the LLM.

   ```mermaid
   sequenceDiagram
    autonumber
    participant Gateway as MCP Gateway Router
    participant TVM as TVM Service
    participant Target as Orders Middleware
    participant Handler as Orders Handler
    participant FS as Local Filesystem
    Note over Gateway: Request routed to query_orders
    Gateway->>TVM: Request capability token<br/>(tool=orders, tenant=tenant_id)
    activate TVM
    TVM-->>Gateway: Returns short-lived TVM capability token
    deactivate TVM
    Gateway->>Target: Forward request<br/>(Header: x-tvm-capability)
    activate Target

    Target->>Target: Cryptographically validate capability<br/>(Signature, TTL, Tenant Scope)

    Target->>Handler: Pass authorized request
    activate Handler

    Handler->>FS: Read data/orders/{tenant-id}.json
    activate FS
    Note over Handler, FS: Prefix-scoped file access guarantees isolation
    FS-->>Handler: Returns tenant orders JSON
    deactivate FS

    Handler-->>Target: Return structured JSON
    deactivate Handler

    Target-->>Gateway: Return structured JSON
    deactivate Target
   ```

   The below sequence diagram depicts the "Orders Target Path" flow. Specifically, it illustrates the Token Vending Machine (TVM) capability model and how the Orders middleware independently validates the short-lived token before reading from the prefix-scoped filesystem

   ![Query_orders](./screenshots/Query_orders.png)

6. **Properties Target Path** (`query_properties`)

   The properties service takes a different approach to authorization: dual-token validation and Row-Level Security (RLS).

   If the gateway routes the request to the properties service, it attaches two headers: a long-lived gateway service token, and the `x-user-token` (the user's original JWT).

   The Properties service middleware intercepts the request and validates _both_ tokens. It ensures the request came from the trusted gateway, and it decodes the user's JWT to extract the `tenant_id`.

   The handler then executes a SQL query against a shared SQLite database (where all tenants' properties are stored in the same table). However, security is enforced at the database driver level: a custom SQLite Authorizer acts as an RLS emulator. If the query attempts to read a row where the `tenant_id` column does not match the JWT's `tenant_id`, the authorizer actively denies the read at the database engine level.

   ```mermaid
   sequenceDiagram
    autonumber
    participant Gateway as MCP Gateway Router
    participant Target as Properties Middleware
    participant Handler as Properties Handler
    participant Authorizer as SQLite Authorizer
    participant DB as SQLite DB (Shared Table)

    Note over Gateway: Request routed to query_properties
    Gateway->>Target: Forward request<br/>(Headers: x-service-token, x-user-token)
    activate Target

    Target->>Target: Validate gateway service token
    Target->>Target: Decode & validate x-user-token (JWT)<br/>Extract tenant_id

    Target->>Handler: Pass authorized request (bound to tenant_id)
    activate Handler

    Handler->>DB: Execute SQL Query (e.g., SELECT * FROM properties)
    activate DB
    Note over DB, Authorizer: SQLite engine triggers authorizer for every row read

    DB->>Authorizer: Check row access (tenant_id column)
    activate Authorizer

    alt Row tenant_id == JWT tenant_id
        Authorizer-->>DB: ALLOW (SQLITE_OK)
    else Row tenant_id != JWT tenant_id
        Authorizer-->>DB: DENY (SQLITE_IGNORE / SQLITE_DENY)
    end
    deactivate Authorizer

    DB-->>Handler: Returns strictly filtered RLS rows
    deactivate DB

    Handler-->>Target: Return structured JSON
    deactivate Handler

    Target-->>Gateway: Return structured JSON
    deactivate Target
   ```

   The below sequence diagram depicts depicting the Properties Target Path flow. It highlights the dual-token validation mechanism and how the custom SQLite Authorizer enforces Row-Level Security (RLS) deep within the database engine itself, filtering out rows that don't belong to the user's tenant:

   ![Query_properties](./screenshots/Query_properties.png)

7. **Synthesis and Response**

   Once the tool execution completes successfully, the retrieved JSON data (from either the Orders or Properties path) is returned back through the gateway to the Chat Service.

   The Chat Service appends this raw tool result to the conversation context and sends the updated thread back to the LLM.

   The LLM synthesizes the static knowledge (from the initial RAG context) and the real-time data (from the tool result) to generate a final, natural-language answer.

   Finally, this response is streamed back to the browser via Server-Sent Events (SSE) and rendered in the UI for the user, concluding the request lifecycle.

   ```mermaid

   sequenceDiagram
    autonumber
    actor User
    participant Browser UI
    participant Chat as Chat Service
    participant Gateway as MCP Gateway
    participant LLM as OpenAI LLM

    Note over Chat, Gateway: Tool execution completes successfully
    Gateway-->>Chat: Returns raw JSON tool result

    Chat->>Chat: Append raw tool result to conversation context

    Chat->>LLM: Send updated thread<br/>(System Prompt + RAG + History + Tool Result)
    activate LLM

    Note over LLM: Synthesizes static knowledge (RAG)<br/>with real-time data (Tool Result)
    LLM-->>Chat: Streams final natural language answer
    deactivate LLM

    Chat-->>Browser UI: Stream response chunks via Server-Sent Events (SSE)

    Note over Browser UI: UI renders markdown response
    Browser UI->>User: Displays final answer
   ```

   The below sequence diagram depicts the Synthesis and Response flow. It highlights how the Chat Service combines static RAG context with dynamic tool results, enriches the prompt, and streams the final natural-language answer back to the user.

   ![Synthesis_and_Response](./screenshots/Synthesis_and_Response.png)
