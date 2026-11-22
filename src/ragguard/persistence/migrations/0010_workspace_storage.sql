CREATE TABLE IF NOT EXISTS managed_documents (
    ragguard_tenant_id TEXT NOT NULL,
    application_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    document_id TEXT NOT NULL,
    namespace TEXT NOT NULL,
    document JSONB NOT NULL,
    recycled BOOLEAN NOT NULL DEFAULT FALSE,
    source_relative_path TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ragguard_tenant_id, application_id, environment, document_id)
);
CREATE INDEX IF NOT EXISTS managed_documents_namespace_idx
    ON managed_documents (namespace, recycled);

CREATE TABLE IF NOT EXISTS workspace_activity (
    activity_id BIGSERIAL PRIMARY KEY,
    kind TEXT NOT NULL CHECK (kind IN ('runs', 'failures', 'repairs')),
    tenant_id TEXT NOT NULL,
    application_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS workspace_activity_scope_idx
    ON workspace_activity (kind, tenant_id, application_id, environment, created_at DESC);
