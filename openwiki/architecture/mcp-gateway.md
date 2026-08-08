# MCP Tool Gateway Architecture

This page covers `2-Multi-Tenant-MCP-Tool-Gateway/`, the repository's newer one-process demonstration. It is intentionally separate from the smaller JWT/SSE design described in [RAG and isolation workflow](../workflows/rag-and-isolation.md).

## Runtime shape

`app/main.py` mounts the browser UI, local identity/JWKS routes, chat API, public Streamable HTTP MCP gateway, internal orders target, TVM, properties MCP target, and `/health`/`/ready`. `app/lifespan.py` creates local keys/secrets, applies migrations and seeds, initializes embedded stores and both tenant RAG collections, then starts the MCP session managers.

```text
Browser --opaque HttpOnly cookie--> chat API --authenticated user context-->
  RAG + history + per-request MCP client --> /mcp gateway
                                      |          |
                              tenant RAG      orders target --> TVM --> scoped order store
                                                 |
                                      properties target --> SQLite RLS emulator
```

## Trust and credential boundaries

The browser receives only a random `mt_session` cookie. User and service JWTs remain server-side, and the verified identity supplies the tenant; there is no arbitrary tenant selector. The public gateway authenticates a user JWT whose audience includes `mcp-gateway`, removes spoofable tenant/user headers, and derives trusted context from signed claims.

The gateway registry exposes exactly `query_orders` and `query_properties`. Their schemas deliberately omit tenant IDs, JWTs, internal headers, database paths, and credentials. Routing then applies target-specific credentials:

- **Orders:** gateway service token → short-lived tenant/tool/request capability → TVM → prefix-scoped order-store credential.
- **Properties:** gateway service token plus an independently validated user-context JWT → tenant-filtered property query.

The target validates its own credential rather than trusting only the gateway. Audit records retain decisions and structural IDs while redacting prompts, tokens, credentials, and secrets (`app/audit/`).

## Data and isolation boundaries

Tenant Markdown under `knowledge/` is indexed into separate ephemeral Chroma collections and checked again after retrieval (`app/agent/rag.py`). Orders use an embedded/fakeredis adapter with key-prefix enforcement. Properties use a disposable SQLite connection, temporary tenant context, a protected view, and an authorizer that denies direct base-table reads (`app/stores/property_store.py`). These are educational substitutes for production identity, Redis ACLs, and PostgreSQL RLS.

## Change guidance

Start with [MCP gateway workflow](../workflows/mcp-gateway.md) before changing authentication, routing, target credentials, or store access. Preserve audience/signature checks, header stripping, capability expiry/request binding, tenant checks at target boundaries, and redacted audit behavior. The raw user JWT passed to the properties target is workshop parity; a production design should use token exchange or an audience-bound actor token. HTTP, insecure development cookies, generated local keys, missing rate limiting/CSRF protection, and in-memory Chroma are not deployment defaults.

Primary sources: `README.md`, `app/main.py`, `app/lifespan.py`, `app/gateway/`, `app/tvm/`, `app/targets/`, `app/stores/`, and `app/agent/`.

# Example of the gateway having detected and blocked an attempt to spoof internal security headers

Running the following command - in the terminal - prints a formatted table of recent audit events:

```bash
ax@MacBookPro 2-Multi-Tenant-MCP-Tool-Gateway % sqlite3 .local/demo.db -header -column "SELECT occurred_at, tenant_id, service, action, target, decision, status_code FROM audit_events ORDER BY occurred_at DESC;"
```

the audit table:

```diff
  occurred_at                       tenant_id  service      action                   target                    decision  status_code
  --------------------------------  ---------  -----------  -----------------------  ------------------------  --------  -----------
  2026-07-17T04:57:07.913456+00:00  tenant-A   chat-agent   chat                     rag-and-mcp               allowed   200
  2026-07-17T04:57:07.910817+00:00  tenant-A   mcp-gateway  query_orders             /internal/tools/orders    allowed   200
  2026-07-16T18:09:46.150901+00:00  tenant-A   mcp-gateway  query_properties         /internal/mcp/properties  allowed   200
  2026-07-16T18:09:14.245809+00:00  tenant-A   mcp-gateway  query_orders             /internal/tools/orders    allowed   200
  2026-07-16T17:54:26.474417+00:00  tenant-A   mcp-gateway  query_orders             /internal/tools/orders    allowed   200
- 2026-07-16T17:54:26.194292+00:00  tenant-A   mcp-gateway  strip_untrusted_context  gateway-interceptor       stripped  200
  2026-07-16T17:51:58.987198+00:00  tenant-A   mcp-gateway  query_orders             /internal/tools/orders    allowed   200
```

That audit log entry (strip_untrusted_context / stripped) indicates that the gateway actively detected and blocked an attempt to spoof internal security headers.

## To try manually spoofing internal headers using curl, follow the below workflow:

Run this from the MCP gateway project while the app is running.

```curl
  cd /Users/ax/Desktop/ANTIGRAVITTY/multi-tenant-agents/2-Multi-Tenant-MCP-Tool-Gateway
```

First, create a fresh Tenant A login. This writes its server-side JWT to browser_sessions:

```curl
  curl -sS \
    -X POST http://127.0.0.1:8000/auth/login \
    -H 'Content-Type: application/json' \
    --data '{"username":"alice@tenant-a.demo","password":"alice-demo"}'
```

Retrieve that JWT locally and create a correlation ID:

```curl
  TOKEN=$(sqlite3 .local/demo.db \
    "SELECT user_token FROM browser_sessions
     WHERE user_id = 'user-tenant-a-alice'
     ORDER BY created_at DESC LIMIT 1;")

  REQUEST_ID=$(uuidgen | tr '[:upper:]' '[:lower:]')
```

Now call the public gateway while pretending to be Tenant B:

```curl
  curl -sS \
    -X POST http://127.0.0.1:8000/mcp/ \
    -H "Authorization: Bearer $TOKEN" \
    -H 'Accept: application/json, text/event-stream' \
    -H 'Content-Type: application/json' \
    -H 'MCP-Protocol-Version: 2025-06-18' \
    -H "X-Request-ID: $REQUEST_ID" \
    -H 'X-Tenant-ID: tenant-B' \
    -H 'X-Tenant-Context: forged-capability' \
    -H 'X-User-Token: forged-user-token' \
    --data '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"query_orders","arguments":{"limit":20}}}'
```

The request should succeed, but only return Tenant A orders because the signed JWT wins and the three forged headers are removed.

Confirm the exact audit events:

```sqlite3
  sqlite3 .local/demo.db -header -column "
  SELECT
      occurred_at,
      request_id,
      tenant_id,
      service,
      action,
      target,
      decision,
      status_code,
      details_json
  FROM audit_events
  WHERE request_id = '$REQUEST_ID'
  ORDER BY occurred_at;"
```

You should see rows:

```curl
  tenant-A  mcp-gateway  strip_untrusted_context  gateway-interceptor       stripped  200
  tenant-A  mcp-gateway  query_orders             /internal/tools/orders    allowed   200
```

details_json should list the stripped header names. A valid bearer token is essential: authentication happens before spoof detection, so an invalid token produces
401 without recording the stripping event.

Finally, clear the shell variable:

```
unset TOKEN
```

## Here is exactly what happened:

### Background

In this architecture, when the gateway receives a request from a client, it verifies their JWT and determines their tenant_id. It then securely forwards that request to internal targets (like the orders or properties targets) by injecting its own trusted HTTP headers, specifically x-tenant-id, x-tenant-context, and x-user-token.

Because those targets trust the gateway to provide the correct tenant context, an attacker might try to bypass the security by sending those headers directly in their HTTP request (e.g., trying to access Tenant B's data by sending x-tenant-id: tenant-B, even if they are only authenticated as Tenant A).

### What the Interceptor Did

The GatewayAuthMiddleware (the "interceptor") sits at the very edge of the gateway and inspects every incoming request. It maintains a strict deny-list of headers:

```python
UNTRUSTED_CONTEXT_HEADERS = {b"x-tenant-id", b"x-tenant-context", b"x-user-token"}
```

When it processed the request logged at 2026-07-16T17:54:26, it found that the client had maliciously (or accidentally) included one or more of these internal headers.

To protect the system, the interceptor made the decision to "strip" (remove) those specific headers from the incoming request before allowing it to proceed. It then recorded this strip_untrusted_context event in the audit log so security teams can see that a spoofing attempt was thwarted.
