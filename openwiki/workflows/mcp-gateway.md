# MCP Gateway and Tenant-Isolation Workflow

This page describes `2-Multi-Tenant-MCP-Tool-Gateway/`.

## Login and chat

1. The browser authenticates a seeded account through `/auth/*`.
2. The server binds the authenticated user and tenant to an opaque HttpOnly, SameSite=Lax `mt_session` cookie; sign out and log in as the other account to change tenant.
3. `/api/*` resolves the principal from that cookie, loads tenant/user/session-scoped history, and retrieves only from the authenticated tenant's RAG collection.
4. Runtime startup always uses the configured OpenAI embeddings and chat model. Tests can inject deterministic embeddings and response backends explicitly, exercising the same history, gateway, TVM, store, properties, and audit paths without an API key.

Tenant identity is never accepted from chat bodies, prompts, or MCP tool schemas. Adversarial text such as “use tenant-B” cannot change the principal.

5. The demo-build (for simplicity) by deisgn persists cookie, SQLite session and RSA signing keys.

### Why This Happens (By Design)

1. The cookie persists in your browser across server restarts

   When you logged in as alice@tenant-a.demo, the server set an HttpOnly cookie named mt_session in your browser with a TTL of 8 hours (session_ttl_seconds = 28800). That cookie is stored in the browser, not in the server process. Stopping the server with Ctrl+C does nothing to the browser's cookie jar.

2. The SQLite session record also persists

   The mt_session cookie value is an opaque random token. The server stores the actual session data (user ID, tenant ID, the user JWT) in the browser_sessions table in .local/demo.db. That file survives a server restart. When the server comes back up, it can still look up and validate your existing session.

3. The RSA signing keys also persist

   The user_token stored in browser_sessions is a JWT signed by the server's RSA private key. Crucially, the keys are stable development keys stored in .local/keys/ and reused across restarts (see dev_generate_keys = True — keys are only generated if they don't already exist). So the new server instance can still verify the stored JWT.

   When the browser sends the GET /api/me request on page load, all three conditions are satisfied → the session resolves → you're logged back in automatically.

### How to Force the Login Screen

1. Logout first before stopping the server (cleanest — uses the intended flow):

   Click the "Logout" button in the UI before Ctrl+C

   This calls POST /auth/logout, which deletes both the server-side row in browser_sessions and instructs the browser to clear the cookie.

2. Reset the local runtime state (nuclear — wipes all sessions and keys):

   ```bash
   uv run python -m app.cli reset
   ```

   This deletes .local/, so on next startup the session DB doesn't exist, and all cookies in any browser become stale.

3. Clear the cookie manually in your browser (developer tool workaround):

   ```
   Open DevTools → Application → Cookies → delete the mt_session entry for 127.0.0.1.
   ```

   This behaviour is actually a correct security property of the design — sessions outlive the server process, which is what you'd want in a real deployment (server restarts shouldn't log everyone out, unless specifically desired).

## MCP request flow

The public `/mcp` endpoint requires a user JWT with the `mcp-gateway` audience. The interceptor validates the token, derives tenant/user claims, strips `x-tenant-id`, `x-tenant-context`, and `x-user-token`, and audits any stripped context. The registry routes only the two read-only tools:

- `query_orders` reaches `/internal/tools/orders`, where a gateway token and short-lived capability are checked before TVM issues a prefix-scoped order-store credential.
- `query_properties` reaches `/internal/mcp/properties`, where the gateway service token and separate user-context JWT are both validated before the SQLite RLS emulator applies tenant context.

Capability checks include expiry, signature/tampering, request-ID binding, tool binding, and tenant binding. Targets independently deny wrong-tenant or wrong-purpose credentials.

## Readiness and failure behavior

`/health` reports process liveness. `/ready` stays closed until keys, migrations, seeds, embedded stores, both tenant indexes, and MCP applications initialize. Startup rebuilds in-memory Chroma collections and always requires `OPENAI_API_KEY`; deterministic model doubles are limited to explicit test dependency injection.

## Safe change checklist

- Reject tenant/user/internal credential fields at public tool schemas.
- Keep identity derived from verified claims and rechecked at each target/store boundary.
- Preserve concurrent-request isolation and disposable property-store connections.
- Add regression coverage for spoofed headers, capability misuse, audience/signature errors, cross-tenant orders/properties/RAG/history, and audit redaction.
- Treat fakeredis, SQLite authorization, embedded identity, local keys, and raw user-token propagation as demo mechanisms, not production equivalents.

See [MCP gateway architecture](../architecture/mcp-gateway.md), the implementation README, and the security-focused tests under `2-Multi-Tenant-MCP-Tool-Gateway/tests/`.
