CREATE TABLE IF NOT EXISTS registered_applications (
    ragguard_tenant_id TEXT NOT NULL,
    application_id TEXT NOT NULL,
    display_name TEXT NOT NULL,
    environment TEXT NOT NULL,
    knowledge_source TEXT NOT NULL CHECK (
        knowledge_source IN ('managed_index', 'external_rag_api', 'observation_only')
    ),
    vector_namespace TEXT,
    query_endpoint_url TEXT,
    query_token_env_var TEXT,
    observation_token_env_var TEXT,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (ragguard_tenant_id, application_id, environment),
    CHECK (
        (knowledge_source = 'managed_index' AND vector_namespace IS NOT NULL)
        OR (knowledge_source = 'external_rag_api' AND query_endpoint_url IS NOT NULL)
        OR knowledge_source = 'observation_only'
    )
);

CREATE INDEX IF NOT EXISTS registered_applications_active_scope_idx
    ON registered_applications (ragguard_tenant_id, active, display_name, environment);

CREATE INDEX IF NOT EXISTS registered_applications_observation_auth_idx
    ON registered_applications (application_id, environment, active)
    WHERE observation_token_env_var IS NOT NULL;