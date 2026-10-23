ALTER TABLE registered_applications
    ADD COLUMN IF NOT EXISTS repair_endpoint_url TEXT;

ALTER TABLE registered_applications
    ADD COLUMN IF NOT EXISTS repair_token_env_var TEXT;
