CREATE TABLE IF NOT EXISTS application_memberships (
    issuer TEXT NOT NULL,
    subject TEXT NOT NULL,
    ragguard_tenant_id TEXT NOT NULL,
    application_id TEXT NOT NULL,
    environment TEXT NOT NULL,
    roles JSONB NOT NULL DEFAULT '[]'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (
        issuer,
        subject,
        ragguard_tenant_id,
        application_id,
        environment
    ),
    FOREIGN KEY (ragguard_tenant_id, application_id, environment)
        REFERENCES registered_applications (
            ragguard_tenant_id,
            application_id,
            environment
        )
        ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS application_memberships_user_scope_idx
    ON application_memberships (
        issuer,
        subject,
        ragguard_tenant_id,
        application_id,
        environment
    );
