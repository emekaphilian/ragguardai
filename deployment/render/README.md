# RAGGuard staging on Render

`staging.yaml` defines an isolated Render project environment with an API,
dashboard static site, and PostgreSQL database. It is deliberately not named
`render.yaml`, so it will not be selected implicitly as a production Blueprint.
Select it explicitly when creating the staging Blueprint. The Blueprint keeps
automatic deploys off; deploys remain manual.

The API and dashboard use separate HTTPS origins. The API gets a generated
session secret and a private-network database connection. New application
registrations remain governed by RAGGuard's existing defaults; this setup does
not grant repair permissions to any connected application.

## Before deploying the Blueprint

1. Confirm the Render workspace and Frankfurt region are appropriate. The
   PostgreSQL `0.1c-256mb` plan is paid; do not create the Blueprint until its
   ongoing cost is accepted. The API uses Render's free web plan, which can
   spin down when idle. The staging PostgreSQL database is separate from
   production and restricted to private-network access.
2. Create a test OIDC client with this exact callback URL:
   `https://ragguard-staging-api.onrender.com/api/v1/auth/callback`.
   Configure the provider's logout/session policy for a test tenant only.
3. During Blueprint setup, enter the OIDC issuer, client ID, client secret, and
   bootstrap administrator subject when prompted. Keep these values in Render's
   secret store. The dashboard uses the OIDC administrator session. The optional
   `RAGGUARD_ADMIN_TOKEN` is deliberately absent; add a staging-only token in the
   Render dashboard only if you later need server-side administrative automation.
4. The generated service hostnames are referenced by the callback, CORS origin,
   and `VITE_API_BASE_URL`. If Render assigns different hostnames, update those
   values and the OIDC provider's registered callback before deploying.
5. Verify that the selected database and application are in the `staging`
   environment, then deploy manually. API startup applies the SQL migrations and
   performs the one-time administrator bootstrap.

Do not copy production secrets, databases, or identity-provider credentials to
staging. Do not run this Blueprint against the production environment.

## Post-deploy verification

- Confirm `GET /api/v1/health` returns the RAGGuard health response.
- Sign in with a test identity and verify the callback returns to the dashboard.
- Confirm the session survives an API restart, expires according to the configured
  session TTL, and is invalidated by CSRF-protected logout.
- Verify an unprovisioned user has no tenant access, a reader cannot perform writes,
  and only the staging bootstrap administrator can manage staging memberships.
- Verify provider-unavailable and invalid-token cases fail closed and do not create
  a session.
- Confirm audit and application records are present after an API restart and that
  no credentials appear in frontend requests or logs.
- Add documents in two application environments with the same document ID, restart
  the API, and verify both bodies remain isolated and queryable only in their own
  vector namespaces. Repeat with two API instances to verify cross-worker visibility.
- Run concurrent ingest, query, recycle, and restore requests from separate
  application environments; verify no document or retrieval result crosses scope.
- Register TrustAssist, BiomedicalRag, and a third staging application; ingest the
  same document ID in each; verify independent queries, restart the API, and repeat
  the checks against multiple API instances. The PostgreSQL CI integration test
  covers the repository and worker-object concurrency path for these cases.
- Submit simultaneous observations, attempt cross-application reads, and attempt a
  repair first without and then with the application's explicit repair capability.
- Take a database backup, restore it into an isolated database, and verify managed
  documents, registrations, and workspace activity before considering recovery proven.

See [`../../docs/deployment.md`](../../docs/deployment.md) for the application
authentication and persistence requirements.
