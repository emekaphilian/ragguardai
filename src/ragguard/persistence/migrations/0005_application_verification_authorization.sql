ALTER TABLE registered_applications
    ADD COLUMN IF NOT EXISTS context_verification_authorized
        BOOLEAN NOT NULL DEFAULT FALSE;

ALTER TABLE registered_applications
    ADD COLUMN IF NOT EXISTS independent_verification_authorized
        BOOLEAN NOT NULL DEFAULT FALSE;
