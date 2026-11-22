# RAGGuardAI — Release Readiness Verification and Evidence Report

**Verification date:** 2026-11-22
**Release candidate:** `7e64383c833162693ebb3bef9b793cf1f712b4c6`
**Branch:** `production-foundation`
**Decision:** **NOT READY**

This report distinguishes local results, GitHub Actions results, and live staging
evidence. A configured test, a test source file, or a YAML parse is not evidence
that a production behavior passed.

## 1. Executive release decision

**NOT READY.** The local Python and frontend checks pass, but the PostgreSQL
integration tests were skipped locally. The pushed GitHub Actions run concluded
`failure` without executing any runner time or providing usable job logs. No
staging deployment, live OIDC verification, or deployed multi-worker test has
been demonstrated.

No release gate is marked `PASS`. The failure of the Actions run is recorded as
an execution/evidence blocker, not as proof of an application defect: all five
jobs report zero runtime and the downloadable log archive is empty.

## 2. Release candidate identification

| Item | Value |
|---|---|
| Repository | `emekaphilian/ragguardai` |
| Branch | `production-foundation` |
| Candidate commit | [`7e64383`](https://github.com/emekaphilian/ragguardai/commit/7e64383c833162693ebb3bef9b793cf1f712b4c6) |
| Commit subject | `fix: pass graph state mappings to LangGraph` |
| Verification date | 2026-11-22 |

The candidate commit and its release-readiness foundation commit are pushed to
the branch. The candidate commit changes LangGraph invocation inputs from a
dataclass instance to a mapping; the local full Python suite passes after this
change.

## 3. System architecture and deployment topology

The repository contains a FastAPI API, a Vite-built dashboard, PostgreSQL
migrations and repositories, and a Render staging Blueprint. The intended
staging topology is an API web service, static dashboard, and isolated
PostgreSQL database, as described in the [Render staging runbook](../deployment/render/README.md)
and [staging Blueprint](../deployment/render/staging.yaml).

**Observed topology:** no staging API, dashboard, or database has been verified
as deployed. The configured API health URL returned HTTP 404. The Blueprint
YAML parses locally, but Render-side Blueprint validation could not be
completed because the Render CLI session is expired (HTTP 401).

CI is configured for PostgreSQL 16. The staging Blueprint requests PostgreSQL
18; that version difference has not been exercised.

## 4. PostgreSQL migration and persistence evidence

- The CI workflow defines a PostgreSQL 16 service and sets
  `RAGGUARD_TEST_DATABASE_URL` in the test job
  ([CI workflow](../.github/workflows/ci.yml)).
- Local `python -m pytest -q` completed with **221 passed, 2 skipped**. The
  skipped cases are the PostgreSQL workspace/concurrency and backup/restore
  integration tests; no database URL, PostgreSQL client utilities, or running
  Docker daemon was available.
- GitHub Actions run [#19](https://github.com/emekaphilian/ragguardai/actions/runs/45039018782)
  concluded `failure`. All five jobs report `0 ms` runner duration. Per-job logs
  were unavailable and the run-log archive was empty. Therefore this run does
  not establish migration or persistence behavior.

**Result:** no successful execution against PostgreSQL is evidenced.

## 5. Multi-application isolation evidence

The local Python suite passed, including unit/API coverage for tenant and
application scoping. The PostgreSQL test source defines a three-application
scenario using TrustAssist, BiomedicalRag, and a third app with repeated
document IDs ([workspace integration test](../tests/integration/test_postgres_workspace_storage.py)).
That PostgreSQL scenario was **skipped locally** and has no successful CI result.
Isolation across deployed API workers has not been tested.

## 6. Transactional and concurrency reliability evidence

Local tests passed, including the concurrent-observation test and repair
rollback coverage. The PostgreSQL integration test defines transaction rollback,
concurrent ingest/query, worker-object visibility, and simulated post-commit
worker restart checks. It did not execute locally because PostgreSQL was
unavailable, and the Actions run supplied no test logs.

**Result:** in-process/local test evidence exists; database transaction and
deployed concurrency behavior remain unverified.

## 7. Backup and recovery evidence

The `pg_dump`/`pg_restore` integration test is present
([backup/restore test](../tests/integration/test_postgres_backup_restore.py)),
but it was skipped because the database URL and client utilities were absent.
No backup artifact, restore target, or restore verification result is recorded.

## 8. Staging infrastructure verification

- Render staging configuration exists and passed a local YAML parse.
- Render CLI Blueprint validation returned HTTP 401 because the CLI token is
  expired.
- `https://ragguard-staging-api.onrender.com/api/v1/health` returned HTTP 404.
- No staging migration, API/dashboard operation, database connectivity, or
  staging acceptance run is evidenced.

The Blueprint has not been deployed. Automatic deploys are intentionally off.

## 9. OIDC and authorization verification

OIDC and authorization unit/API tests are included in the passing local Python
suite. No live identity provider, test OIDC client, callback, browser session,
CSRF logout, or staging membership/repair authorization flow was verified. The
required staging OIDC settings and test identity are not available to this
verification.

## 10. Multi-worker and distributed-operation verification

The PostgreSQL integration test creates multiple `Workspace` instances to
exercise shared database visibility, but it was skipped locally. No deployed
API worker pool, cross-worker session/activity test, or worker restart under
traffic has been verified.

## 11. Known limitations and unresolved risks

1. The GitHub Actions run for the candidate commit failed before usable job
   execution evidence was produced; its logs are unavailable.
2. PostgreSQL persistence, transaction, concurrency, and backup/restore tests
   remain unexecuted.
3. Live staging is unavailable at the configured health URL; Render CLI
   authentication has expired.
4. OIDC provider/client settings and test identities have not been configured
   for staging.
5. PostgreSQL 16 in CI and PostgreSQL 18 in the staging Blueprint have not been
   shown to be compatible by executed integration evidence.
6. Local Python verification used Python 3.14; CI is configured for Python 3.11.
   The CI run did not provide evidence for that runtime.
7. The Render API uses a free web-service plan that may spin down; its suitability
   for any production SLO has not been assessed.

## 12. Gate-by-gate acceptance results

Statuses: `PASS` requires successful execution and traceable evidence; `FAIL`
requires an executed verification that exposed a defect; `BLOCKED` means a
prerequisite or usable execution evidence is unavailable; `NOT_RUN` means no
attempt was made.

| Gate | Verification | Status | Evidence / outstanding requirement |
|---|---|---|---|
| G1 | PostgreSQL foundation | **BLOCKED** | CI run failed with zero runner time and no job logs; local PostgreSQL integration tests skipped. Obtain a successful PostgreSQL CI run with logs. |
| G2 | Application isolation | **BLOCKED** | Local tests pass; three-app PostgreSQL and deployed cross-worker scenarios are unverified. |
| G3 | Transactional reliability | **BLOCKED** | Local reliability tests pass; PostgreSQL rollback and concurrency scenario did not execute. |
| G4 | Data recovery | **BLOCKED** | Backup/restore test skipped; no successful backup and restore evidence. |
| G5 | Staging infrastructure | **BLOCKED** | Blueprint parses as YAML, but Render validation is unauthorized and health endpoint returned 404; no live deployment. |
| G6 | Identity and authorization | **BLOCKED** | Local tests pass; no live OIDC session, tenant/application grant, or repair-authorization evidence. |
| G7 | Distributed operation | **BLOCKED** | No PostgreSQL multi-worker test result or deployed multi-worker verification. |

## 13. Final release recommendation and sign-off

**Recommendation: do not promote to production.** The evidence currently supports
only local test-suite results, not a staging-verified release candidate.

Before reconsidering release:

1. Restore GitHub Actions execution and obtain a successful, inspectable CI run
   including both PostgreSQL integration tests.
2. Re-authenticate the Render CLI and validate/deploy the isolated staging
   Blueprint.
3. Configure a test-only OIDC client and identities through the secure staging
   secret store; do not put credentials in this report or source control.
4. Execute the staging isolation, authorization, backup/restore, and multi-worker
   checklist and record timestamps, deployed SHA, service URLs, and results.
5. Obtain explicit technical and operational sign-off after all seven gates pass.

**Release sign-off:** pending. No production approval is recorded.
