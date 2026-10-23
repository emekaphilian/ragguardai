ALTER TABLE registered_applications
    ADD COLUMN IF NOT EXISTS observation_token_hash TEXT;

CREATE INDEX IF NOT EXISTS registered_applications_observation_hash_auth_idx
    ON registered_applications (application_id, environment, active)
    WHERE observation_token_hash IS NOT NULL;
