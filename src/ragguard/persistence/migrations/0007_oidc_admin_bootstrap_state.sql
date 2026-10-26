CREATE TABLE IF NOT EXISTS auth_bootstrap_state (
    bootstrap_key TEXT PRIMARY KEY,
    completed_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
