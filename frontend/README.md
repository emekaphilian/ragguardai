# RAGGuard Console

React + Vite reliability control center for RAGGuard.

## NLP Narrator
Every major dashboard includes the reusable `NarratorPanel`. It calls `POST /api/v1/narrate` and converts technical health signals into a short, non-technical explanation. The backend narrator is deterministic by default so dashboard summaries remain stable and auditable. It can later be replaced by an LLM provider without changing the UI contract.

## Run

```bash
npm install
npm run dev
```

Open http://localhost:5173.
Set `VITE_API_BASE_URL` when the API is not on localhost:8000. Set
`VITE_RAGGUARD_TENANT_ID` can optionally override the API tenant scope; by
default the API uses its configured `RAGGUARD_SERVICE_TENANT` so observation
reads and writes share the same internal tenant. The override is a tenant scope
identifier, not an authentication secret. The Query Runs page polls `/runs`
every four seconds. For a deployed frontend, set `VITE_API_BASE_URL` in its
build environment and rebuild the static site; Vite embeds it at build time.
