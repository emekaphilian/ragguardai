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
Set `VITE_API_BASE_URL` when the API is not on localhost:8000.
