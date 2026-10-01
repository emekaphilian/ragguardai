CREATE TABLE IF NOT EXISTS observations (
    observation_id TEXT PRIMARY KEY,
    ragguard_tenant_id TEXT NOT NULL,
    application_id TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL,
    status TEXT NOT NULL,
    query TEXT NOT NULL,
    evaluation JSONB NOT NULL,
    observation JSONB NOT NULL,
    failure JSONB,
    recovery JSONB
);

CREATE INDEX IF NOT EXISTS observations_internal_tenant_created_idx
    ON observations (ragguard_tenant_id, created_at DESC);

CREATE INDEX IF NOT EXISTS observations_application_created_idx
    ON observations (application_id, created_at DESC);

CREATE INDEX IF NOT EXISTS observations_status_created_idx
    ON observations (status, created_at DESC);
