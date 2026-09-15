# ADR 002 — Agent Orchestration

Keep LangGraph outside the core business layer. Agent nodes call deterministic services. A sequential fallback makes the project runnable without an agent framework.
