# Deployment

## Local

Run the pipeline directly or through Docker Compose.

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
