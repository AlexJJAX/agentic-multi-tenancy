# Cloud workshop mapping

This implementation translates a cloud multi-tenant agent workshop into a one-process local
system. The goal is to preserve trust decisions and credential shapes while making the project
reproducible without a cloud account.

| Local component | Workshop analogue | Preserved property | Deliberate gap |
| --- | --- | --- | --- |
| Identity routes + RSA issuer | Cognito/OIDC | Signed user identity, audiences, JWKS | No hosted MFA, federation, or rotation |
| FastAPI + LangChain agent | Pooled agent runtime | Shared compute, identity-derived scope | One local process |
| `/mcp` FastMCP app | Agent gateway | Public tools, schema boundary, user auth | No managed gateway controls |
| Gateway interceptor | Request interceptor | Verify token, strip spoofed context | Process-local middleware |
| Orders HTTP adapter | Lambda target | Service token + signed tenant capability | No isolated function runtime |
| TVM + fakeredis adapter | Token-vending/store credential | Short-lived prefix/operation scope | Not native Redis ACL |
| Properties FastMCP target | Protected data service | Service auth + separately verified actor | Local mount |
| SQLite protected view | Aurora PostgreSQL RLS | Connection-scoped filtered access | Emulation, not native RLS |

## Why the mapping is useful

Collapsing deployment must not collapse authority. The gateway cannot query either store
directly. Orders and properties validate different credentials because they represent
different target contracts. The model never receives the token configuration or a tenant
selector. These properties remain meaningful when components share an event loop.

## Where local equivalence ends

Fakeredis proves adapter-level prefix enforcement but not Redis TLS, ACL lifecycle, cluster
behavior, or operational isolation. SQLite demonstrates connection-local policy discipline but
not PostgreSQL roles, `SET LOCAL`, pool hygiene, or native RLS guarantees. Generated keys prove
signing and verification flows but not managed key custody or rotation.

For a cloud deployment, split the mounts into independently permissioned services, replace the
identity provider and data stores, use private networking, rotate audience-bound credentials,
export distributed traces, and test the managed services directly. The local interfaces are
intended to make those replacements explicit rather than imply drop-in equivalence.
