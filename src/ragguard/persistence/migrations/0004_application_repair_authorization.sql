ALTER TABLE registered_applications
    ADD COLUMN IF NOT EXISTS repair_authorized BOOLEAN NOT NULL DEFAULT FALSE;