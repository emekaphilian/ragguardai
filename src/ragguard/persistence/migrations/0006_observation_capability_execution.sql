ALTER TABLE observations
    ADD COLUMN IF NOT EXISTS capability_execution JSONB NOT NULL DEFAULT '{}'::jsonb;
