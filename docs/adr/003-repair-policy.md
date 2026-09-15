# ADR 003 — Deterministic Repair Policy

The system should not allow an LLM to execute arbitrary repairs. Failure modes map to an allow-list of repair types, and validation decides whether a repair is promoted.
