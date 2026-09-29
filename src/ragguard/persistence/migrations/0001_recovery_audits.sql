CREATE TABLE IF NOT EXISTS recovery_audits (
    recovery_id TEXT PRIMARY KEY,
    ragguard_tenant_id TEXT,
    external_tenant_id TEXT,
    application_id TEXT,
    started_at TIMESTAMPTZ NOT NULL,
    final_status TEXT NOT NULL,
    record JSONB NOT NULL
);

CREATE INDEX IF NOT EXISTS recovery_audits_internal_tenant_started_idx
    ON recovery_audits (ragguard_tenant_id, started_at DESC);

CREATE INDEX IF NOT EXISTS recovery_audits_application_started_idx
    ON recovery_audits (application_id, started_at DESC);

CREATE INDEX IF NOT EXISTS recovery_audits_external_tenant_started_idx
    ON recovery_audits (external_tenant_id, started_at DESC);
