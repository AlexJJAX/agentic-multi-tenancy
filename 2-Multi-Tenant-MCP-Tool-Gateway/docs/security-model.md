# Security model

## Assets and invariants

The protected assets are tenant documents, order records, property rows, conversation history,
identity tokens, service credentials, signing keys, and audit integrity. The central invariant
is stronger than “the model should not leak”: no model-controlled input can select or enlarge
tenant scope.

Tenant identity originates only in a verified RSA-signed user JWT. Authentication boundaries
normalize the compatibility claim, reject ambiguity, validate issuer, signature, time,
audience, authorized party, subject, and active tenant status. Browser and MCP request schemas
do not accept a tenant ID.

## Threat model

The project explicitly tests these attacker capabilities:

- A logged-in Tenant A user sends Tenant B IDs or prompt-injection instructions.
- A client supplies fake `x-tenant-id`, user-context, request, or authorization headers.
- A valid user token is replayed at a service-only target.
- A service token is replayed for the wrong audience or scope.
- A tenant capability is expired, modified, reused for another tool, or paired with another
  request ID.
- Store code is asked for a key outside the signed Redis prefix.
- Property code attempts a base-table read instead of the tenant-protected view.
- A user reuses another tenant's session ID or races concurrent scoped requests.

Denial at one layer is not the sole control. Identity is revalidated at the gateway, target
credentials are purpose-bound, and the stores enforce the final data partition.

## Credential separation

User, gateway-service, orders-service, tenant-capability, and store-credential tokens use
distinct audiences, parties, scopes, issuers where appropriate, and short lifetimes.
Downstream services validate the credential intended for them instead of trusting the caller's
network location or mount path.

The 60-second capability TTL bounds replay exposure while allowing one gateway-to-target call
and small clock/processing delays. The store credential is shorter because it is needed only
during a single orders read. TTLs limit but do not eliminate replay; production would add
audience-specific nonce tracking for high-risk operations.

## Data-plane enforcement

RAG combines separate collections, an explicit tenant metadata filter, and post-retrieval
checks. History repositories require tenant, user, and session together. Orders require a
signed prefix for every embedded Redis operation. Properties create a disposable
connection-local scope, expose a protected view, and deny direct base-table reads.

The properties pattern is an emulator for PostgreSQL RLS, not a claim of equivalent security.
SQLite authorizers and temporary tables prove the call discipline locally; they do not provide
the operational hardening, role model, or concurrency semantics of PostgreSQL.

## Secrets and observability

Browser responses expose an opaque session cookie, public record IDs, citations, tool names,
and a correlation ID. Audits keep IDs, action, decision, status, latency, and redacted
structural details. They omit prompts, responses, cookies, JWTs, capabilities, store
credentials, private keys, service secrets, and API keys.

Local generated keys and runtime secrets live under ignored `.local/`. Checked-in
`data/secrets.json` contains only non-secret identifiers; runtime secret values are generated
separately. Production keys belong in a managed KMS/HSM-backed signer and secrets manager.

## Residual risks

- HTTP and non-secure cookies are acceptable only on localhost.
- A compromised application process can read its in-memory principals and generated local
  credentials.
- Process-local JWKS caches do not implement full issuer outage and rotation policy.
- The demo has no rate limiting, anomaly detection, CSRF token, or tenant administration path.
- Prompt injection can still affect which *allowed* read tool is called or how a result is
  summarized. It cannot add a tool or change datastore scope, but output validation remains
  necessary.
- Audit rows are not append-only or externally anchored.

These are deliberate portfolio boundaries. A production review would add a data-flow threat
model, penetration testing, dependency scanning, SAST, secret scanning, and operational
incident playbooks.
