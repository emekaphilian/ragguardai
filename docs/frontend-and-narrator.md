# RAGGuard Frontend and NLP Narrator

RAGGuard's frontend is an AI reliability control center rather than a normal chatbot. It exposes Overview, Query Lab, Live Runs, Failures, Repairs, Evaluations, Documents, Indexes and Settings.

## NLP Narrator

Every major screen has a plain-language narrator panel. It explains what the metrics mean, highlights warnings, and tells an operator whether immediate attention is suggested. The current implementation is deterministic and auditable; an LLM provider can be added later behind the same `/api/v1/narrate` contract.

The narrator deliberately avoids claiming that a repair succeeded merely because it ran. Repair success remains a post-validation state.
