# Deployment

## Local

Run the pipeline directly or through Docker Compose.

Human-user API routes require an explicit authentication mode. For local
development and tests, `RAGGUARD_AUTH_MODE=development_headers` enables the
development identity headers. This mode is rejected in production. The default
mode is `disabled`, which fails closed for human-user routes.

### OIDC login and server sessions

Set `RAGGUARD_AUTH_MODE=oidc` to enable OpenID Connect authorization-code flow
with PKCE. Configure these values as server-side secrets/settings:

```text
RAGGUARD_OIDC_ISSUER=https://<trusted-provider-issuer>
RAGGUARD_OIDC_CLIENT_ID=<client-id>
RAGGUARD_OIDC_CLIENT_SECRET=<client-secret>
RAGGUARD_OIDC_TOKEN_AUTH_METHOD=client_secret_basic
RAGGUARD_OIDC_REDIRECT_URI=https://<api-host>/api/v1/auth/callback
RAGGUARD_FRONTEND_URL=https://<dashboard-origin>
RAGGUARD_FRONTEND_ORIGINS=https://<dashboard-origin>
RAGGUARD_SESSION_SECRET=<at-least-32-random-characters>
RAGGUARD_OIDC_BOOTSTRAP_ADMIN_SUBJECT=<exact-id-token-sub>
RAGGUARD_OIDC_BOOTSTRAP_ADMIN_TENANT=<configured-ragguard-tenant>
RAGGUARD_AUDIT_BACKEND=postgres
RAGGUARD_DATABASE_URL=<postgres-connection-string>
```

Register the exact callback URL and client ID with the identity provider. RAGGuard
uses provider discovery, checks the discovered issuer and HTTPS endpoints, then
verifies the ID-token signature, issuer, audience, authorized party when present,
expiration, issued-at time, and per-login nonce. Sessions contain only an opaque
HttpOnly cookie identifier; session data and tenant grants are stored in PostgreSQL.
The API requires a strong session secret and PostgreSQL when OIDC mode starts.
Use `client_secret_post` if that is the method required by the configured provider.

RAGGuard owns tenant membership and roles. The configured bootstrap subject is
granted `admin` in the bootstrap tenant once, if it has no existing grant. A
workspace admin can manage grants through `PUT` and `DELETE
/api/v1/admin/tenant-memberships`; role changes never come from identity-provider
role claims or browser headers. Roles accepted are `reader`, `operator`, `admin`,
`owner`, and `workspace_admin`. Readers are restricted to read requests; workspace
changes require an operator or admin role; administrative routes require an admin,
owner, or workspace-admin grant for the selected tenant.

All browser writes use the session CSRF token returned by
`GET /api/v1/auth/session`. Browser requests include credentials and the
`X-CSRF-Token` header. Set `RAGGUARD_SESSION_COOKIE_SAMESITE=none` and
`RAGGUARD_SESSION_COOKIE_SECURE=true` only when the actual deployment requires a
cross-site cookie; otherwise keep the default `lax`. `RAGGUARD_FRONTEND_ORIGINS`
must contain exact trusted origins. Do not use wildcard CORS origins with cookies.

The dashboard onboarding and credential-rotation requests use the authenticated
session; they no longer send `RAGGUARD_ADMIN_TOKEN` from the browser. The separate
server-side bearer token remains available for controlled administrative automation.
Observation requests continue to use their own application-specific credentials.
`trusted_proxy` remains unimplemented and fails closed.

## Recovery audit persistence

The API uses in-memory repositories by default for local development. The
production Docker image selects PostgreSQL with `RAGGUARD_AUDIT_BACKEND=postgres`;
configure `RAGGUARD_DATABASE_URL` as a secret in the hosting environment. The
PostgreSQL driver is installed by the production image. On startup, the API
applies the checked-in SQL migrations before accepting requests.

```powershell
python -m pip install ".[postgres]"
$env:RAGGUARD_AUDIT_BACKEND = "postgres"
$env:RAGGUARD_DATABASE_URL = "postgresql://user:password@localhost:5432/ragguard"
$env:PYTHONPATH = ".\src"
python .\scripts\migrate_audit_db.py
```

`RecoveryAuditRepository` and `ObservationRepository` are the application-facing
contracts. PostgreSQL stores recovery audit records and evaluated observation
history separately, with JSONB payloads and indexed RAGGuard tenant, application,
status, and creation-time columns. Observation storage uses RAGGuard's internal
tenant context; it does not store a customer tenant identifier from the source
application. Observation history is not pruned automatically; it remains until
a future, explicitly authorized administrative clear operation.

The explicit clear operation is `DELETE /api/v1/admin/history`. It requires a
separate server-side `RAGGUARD_ADMIN_TOKEN` bearer credential and the
`X-Confirm-Delete: clear-all-history` header. It clears observation records,
recovery audits, and in-process workspace run/failure/repair history. It is
disabled when the admin token is not configured. Never expose this token in the
frontend.

Recovery history is returned in pages:

```text
GET /api/v1/recoveries?page=1&page_size=50
```

The response includes `items`, `page`, `page_size`, `total`, and `has_next`.
`RAGGUARD_AUDIT_MAX_PAGE_SIZE` defaults to 100 and bounds page requests.

Retention is explicit; the API does not prune data at startup. Configure
`RAGGUARD_AUDIT_RETENTION_DAYS` (default 90) and run the cleanup command during
a scheduled maintenance window. It deletes only completed audit records older
than the configured cutoff; active `running` records are preserved. The event
bus keeps its recent in-process buffer according to
`RAGGUARD_EVENT_RETENTION_DAYS` (default 30).

## Application registry and adapters

`registered_applications` is the PostgreSQL source of truth for application,
environment, integration mode, and knowledge-source configuration. Startup
applies its migration. Configured tenant policies are inserted as
managed-index registrations only when no matching registration exists; the
registry can also be bootstrapped explicitly with `POST
/api/v1/admin/applications/bootstrap-configured`.

The tenant-scoped `GET /api/v1/applications` endpoint returns active public
registration metadata for Query Lab. It never returns credential values or
environment-variable references. Administrators can use the following routes
with `Authorization: Bearer $RAGGUARD_ADMIN_TOKEN`:

```text
GET    /api/v1/admin/applications?ragguard_tenant_id=<tenant>
PUT    /api/v1/admin/applications
DELETE /api/v1/admin/applications/<tenant>/<application>/<environment>
```

For guided, observation-only onboarding, the Connect Application wizard calls
`POST /api/v1/admin/applications/onboard`. It creates a registration with repair,
context access, and independent verification disabled, then returns a
high-entropy `RAGGUARD_OBSERVATION_TOKEN` once. Save it in the source
application's secret manager and configure the observer to send it as a bearer
token. In OIDC mode, the wizard authorizes registration and rotation through the
signed-in workspace administrator session. `RAGGUARD_ADMIN_TOKEN` remains
server-side for controlled administrative automation; without an authorized OIDC
admin session or that server token, these operations are unavailable.

The wizard marks an application connected only after it receives and evaluates
a real observation. It does not send a synthetic test request to the source
application. Credential rotation is available to administrators at
`POST /api/v1/admin/applications/<tenant>/<application>/<environment>/observation-credential`;
the new token is shown once and immediately invalidates the previous
application-specific credential.

The default in-memory backend is for local development: registrations and
observation credentials are lost when the process restarts. Production
deployments should use `RAGGUARD_AUDIT_BACKEND=postgres` and
`RAGGUARD_DATABASE_URL` so application registrations and credential hashes
persist. Only SHA-256 hashes of generated application credentials are stored.

Registrations support `managed_index`, `external_rag_api`, and
`observation_only`. Managed indexes specify a `vector_namespace`. External
adapters use an HTTPS `query_endpoint_url` implementing contract v1: accept
`contract_version`, `query`, `top_k`, and `method`; return an answer, retrieved
chunk IDs/scores, retrieval method, latency, and embedding-degradation status.
RAGGuard rejects endpoints resolving to non-public IP addresses and does not
follow redirects.

Store external API token values only as server-side environment variables. The
database stores references such as `SUPPORTBOT_QUERY_TOKEN` in
`query_token_env_var`; the frontend receives neither the reference nor its
value. Per-application observation credentials use the same pattern through
`observation_token_env_var`. The legacy shared
`RAGGUARD_SERVICE_TOKEN` remains supported during migration.

## Recovery replay

`POST /api/v1/replays` accepts a recovery ID and defaults to `dry_run`. Replay
requires a persisted observation snapshot; records created before snapshots
were enabled return a conflict response. The snapshot contains the external
observation fields (query, chunk IDs/scores, answer, and source metadata), but
does not include retrieved chunk text. It is stored for replay and is omitted
from normal audit API responses, so database access and retention policy should
be treated as sensitive-data controls.

Dry-run reconstructs the observation and executes the bounded graph without
repair capabilities or access to a production index. `mode: "execute"` is
disabled unless an explicitly isolated replay service is configured. Replays
read the original audit record but do not modify it or production retrieval
state.

```powershell
$env:PYTHONPATH = ".\src"
python .\scripts\prune_recovery_audits.py
```

## AWS direction

A target production topology is:

S3 → ingestion/processing → RAGGuard API → Bedrock + vector DB + metadata store → CloudWatch.

Terraform in this repository is a starter infrastructure layer. It should be validated and hardened before production use.
