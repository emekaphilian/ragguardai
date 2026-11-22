# RAGGuardAI staging and production readiness

Production deployment remains separate until all four staging gates pass.

## Current verification snapshot

| Gate | Local evidence | Remaining release evidence |
|---|---|---|
| Database | Migration unit tests pass. PostgreSQL persistence and `pg_dump`/`pg_restore` tests are wired into CI. | Run the two PostgreSQL integration tests against the CI service or a disposable PostgreSQL instance; inspect the CI result. |
| Multi-application isolation | Unit and API tests cover application scope and cross-application query rejection. PostgreSQL scenarios register TrustAssist, BiomedicalRag, and a third app with identical document IDs. | Execute the PostgreSQL scenario and verify it on separate deployed API instances. |
| Reliability | Local suite covers concurrent observation submissions, failed repair execution, rollback, and atomic-ingestion failure behavior. | Execute PostgreSQL concurrent ingest/query and database-trigger failure tests; verify worker restart behavior in staging. |
| Live staging | A Render staging Blueprint and post-deploy checklist are present. | Deploy the API, dashboard, and isolated PostgreSQL database; configure a test OIDC client; run the checklist below. |

The latest local run was **221 passed, 2 skipped**. The skipped tests are the PostgreSQL workspace/concurrency and backup/restore integration tests; they require `RAGGUARD_TEST_DATABASE_URL` and PostgreSQL client utilities. This environment has no test database URL and no running Docker daemon. The configured staging health endpoint did not return a usable response, and no Render or OIDC credentials are configured here.

## Gate 1 — Database

Run `python -m pytest -q tests/unit/test_postgres_migrations.py tests/integration/test_postgres_workspace_storage.py tests/integration/test_postgres_backup_restore.py` with `RAGGUARD_TEST_DATABASE_URL` pointing only to a disposable test database. Confirm migrations apply to an empty database and can be reapplied safely. Confirm a new workspace instance reads persisted documents and activity. Confirm a failed multi-document transaction leaves no partial rows. Confirm the backup test restores managed documents, registrations, and activity into a separate database.

CI provisions PostgreSQL 16 and installs `pg_dump`/`pg_restore` for these tests. A green local-only test suite is not a substitute for a green run of the PostgreSQL cases.

## Gate 2 — Application and tenant isolation

Register TrustAssist, BiomedicalRag, and a third independent integration in the staging tenant, each with its own vector namespace. Ingest an identical document ID in every application. Verify each application returns only its own content. Try application and environment overrides outside the caller's grants and verify they are rejected. Repeat the checks across different RAGGuard tenants.

The integrations use the generic RAG observation and adapter contracts. No app-specific behavior should be required by RAGGuard's core.

## Gate 3 — Reliability and recovery

Exercise concurrent ingest and query traffic from distinct API workers while submitting simultaneous observations. Restart one worker during traffic and confirm committed documents remain queryable from the other worker. Force an ingestion transaction to fail and verify the whole batch is absent. Force a repair execution and validation failure; verify rollback preserves the original retrieval index and recovery audit records the failure.

Take a PostgreSQL backup, restore it into a separate database, and verify registrations, managed documents, workspace activity, and audit history. Record the backup timestamp, restore target, and verification result before passing the gate.

## Gate 4 — Live staging

Follow [the Render staging runbook](../deployment/render/README.md). Use a dedicated staging database, test OIDC issuer/client, and test identities. Verify sign-in, tenant and application memberships, observation delivery from all three integrations, repair denial without explicit capability, repair success only when both user role and application capability allow it, and audit history after an API restart.

Record the deployed commit, migration result, CI run, OIDC provider, API/dashboard URLs, backup/restore result, and each checklist outcome. Do not promote to production while any check is failed or unverified.
