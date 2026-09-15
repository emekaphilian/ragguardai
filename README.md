# RAGGuard

**Production-oriented RAG Failure Detection & Auto-Repair System**

RAGGuard is an observability and remediation platform for Retrieval-Augmented Generation systems. It does not merely report that a RAG pipeline failed: it evaluates retrieval and answer quality, identifies the likely failure mode, selects an approved repair, validates the result, and records what happened.

> **Ingest → Retrieve → Evaluate → Detect → Diagnose → Repair → Validate → Observe**

The project also includes a React/Vite reliability control center with embedding diagnostics and an NLP Narrator that explains technical dashboard results in plain language.

---

## What RAGGuard does

A typical RAGGuard run follows this sequence:

```text
User query
    ↓
Retrieve relevant documents
    ↓
Evaluate retrieval and answer quality
    ↓
Detect a failure, if present
    ↓
Diagnose the likely root cause
    ↓
Select an approved repair
    ↓
Execute the repair
    ↓
Validate whether quality improved
    ↓
Promote, roll back, or escalate
    ↓
Record metrics and audit information
```

The system explicitly measures signals such as:

- Context precision and recall.
- Faithfulness and answer relevancy.
- Citation accuracy.
- Retrieval latency.
- Index freshness.
- Chunk duplication and fragmentation.
- Embedding dimension, norm statistics, drift, and duplicate vectors.
- Repair improvement and rollback status.

---

## Architecture at a glance

```text
                         RAGGuard
                            │
              ┌─────────────┴─────────────┐
              │                           │
        React frontend              FastAPI API
              │                           │
              │                    ┌──────┴──────┐
              │                    │             │
              │               LangGraph    API services
              │                    │
              │                    ▼
              │             Workflow state
              │                    │
              │        ┌───────────┼───────────┐
              │        ▼           ▼           ▼
              │    Retrieve     Evaluate     Detect
              │        │           │           │
              │        └───────────┼───────────┘
              │                    ▼
              │                Diagnose
              │                    │
              │                    ▼
              │                  Repair
              │                    │
              │                    ▼
              │                 Validate
              │              ┌─────┴─────┐
              │              ▼           ▼
              │           Promote     Escalate
              │
              ▼
        NLP Narrator
              │
              ▼
       Plain-language
        explanations

        ┌─────────────────────────────────┐
        │          RAGGuard Core           │
        │                                  │
        │ ingestion · retrieval · metrics │
        │ detection · diagnosis · repair  │
        │ validation · observability       │
        └─────────────────────────────────┘
```

---

## LangGraph’s role

LangGraph is **not RAGGuard itself**. It is the optional orchestration layer that coordinates the stages, agents, tools, and shared workflow state.

The core domain logic is independent of LangGraph. A dependency-free sequential runner is included so the project can be demonstrated offline, while LangGraph remains an orchestration adapter.

### The separation

**RAGGuard core answers:**

- How retrieval works.
- How precision, recall, faithfulness, and relevancy are calculated.
- How failure modes are represented.
- How a failure is diagnosed.
- Which repairs are allowed.
- How repairs are validated and promoted.

**LangGraph answers:**

- What should run next.
- Which path should be taken after a failure.
- What state should move between stages.
- Whether the workflow should retry, escalate, or finish.

Conceptually:

```text
                Orchestration
                  LangGraph
                      │
                      ▼
              Shared workflow state
                      │
                      ▼
                 RAGGuard core
```

The same core services can run through either orchestration path:

```text
Sequential runner ─┐
                   ├──► RAGGuard core services
LangGraph runner ──┘
```

This design avoids coupling every business operation to an agent framework and makes testing, offline demonstrations, and future orchestration changes easier.

---

## Agent workflow

RAGGuard can expose specialized workflow agents or node wrappers for:

```text
                    ┌─────────────────┐
                    │  Orchestrator   │
                    │   LangGraph     │
                    └────────┬────────┘
                             │
        ┌────────────────────┼────────────────────┐
        ▼                    ▼                    ▼
   Retrieval Agent     Evaluation Agent     Detection Agent
        │                    │                    │
        └────────────────────┼────────────────────┘
                             ▼
                      Diagnosis Agent
                             │
                             ▼
                        Repair Agent
                             │
                             ▼
                     Validation Agent
                             │
                       ┌─────┴─────┐
                       ▼           ▼
                    Promote     Escalate
```

The agents coordinate operations; they do not bypass the repair policy. Repairs remain allow-listed and validation remains the authority that decides whether a repair is promoted.

### Shared workflow state

A run may carry state similar to:

```json
{
  "query": "What is the refund policy?",
  "retrieved_chunks": [],
  "evaluation": {
    "context_recall": 0.61,
    "context_precision": 0.54,
    "faithfulness": 0.67
  },
  "failure": {
    "detected": true,
    "type": "LOW_CONTEXT_RECALL",
    "severity": "HIGH"
  },
  "diagnosis": {
    "root_cause": "Relevant policy content was missed by vector retrieval",
    "confidence": 0.94
  },
  "repair": {
    "strategy": "HYBRID_RETRIEVAL",
    "status": "completed"
  },
  "validation": {
    "before_score": 0.40,
    "after_score": 0.86,
    "promoted": true
  }
}
```

---

## NLP Narrator

RAGGuard includes an NLP Narrator for every major dashboard and investigation view. The narrator converts technical telemetry into short, simple explanations for non-technical users.

For example, the system may record:

```text
Failure: LOW_CONTEXT_RECALL
Recall: 0.61
Diagnosis: Vector retrieval missed a relevant policy chunk
Repair: HYBRID_RETRIEVAL
Validation: 0.61 → 0.88
```

The narrator can explain this as:

> The system initially missed some important information needed to answer this question. It switched to a broader search method, found the missing information, and improved the answer quality.

The narrator is separate from LangGraph:

```text
RAGGuard core      → performs the operations
LangGraph          → coordinates workflow execution
NLP Narrator       → explains results in simple language
React frontend     → presents the system to users
```

The starter implementation uses deterministic summaries so the UI works without an LLM or external API key. A production deployment can replace the implementation with a Bedrock-hosted model while preserving the same API contract.

---

## Frontend: reliability control center

The React/Vite frontend is designed as an AI reliability and SRE console rather than a conventional chatbot.

### Main screens

- **Overview:** system health, retrieval trends, active incidents, repairs, and embedding health.
- **Query Lab:** submit a question and inspect the answer, context, scores, citations, and repair outcome.
- **Live Runs:** watch Retrieve → Evaluate → Detect → Diagnose → Repair → Validate progress in real time.
- **Failures:** investigate root cause, evidence, severity, affected queries, and recommended repairs.
- **Repairs:** inspect repair plans, before/after metrics, validation, rollback, and promotion status.
- **Evaluations:** compare retrievers, index versions, repair strategies, and benchmark runs.
- **Documents & Indexes:** inspect ingestion, chunking, freshness, index versions, and embedding health.
- **Settings:** environment, thresholds, policies, integrations, and access controls.

### Embedding and index health

The dashboard includes embedding-specific signals:

```text
INDEX HEALTH

Documents indexed:       1,284
Total chunks:            18,920
Last refresh:            2 minutes ago
Stale documents:         14
Duplicate chunks:        3.2%
Embedding model:         text-embedding-3-large
Index version:           v18

EMBEDDING DIAGNOSTICS

Dimension:               3,072
Indexed vectors:         18,920
Average norm:            0.998
Norm standard deviation: 0.031
Zero vectors:            0
Duplicate vectors:       606
Centroid drift:          0.084
Nearest-neighbor score:  0.91
Embedding latency:       42.6 ms
Estimated storage:       226.4 MB
```

These signals help detect malformed vectors, accidental model changes, duplicate content, distribution drift, over-concentrated vector spaces, and operational capacity problems.

### Failure investigation

```text
LOW CONTEXT RECALL · HIGH

Query
“What is the refund deadline for enterprise customers?”

Evaluation
Context recall:  0.41
Precision:       0.83
Faithfulness:    0.92
Overall:         0.71

Root cause
Poor retrieval coverage

Repair plan
✓ Hybrid retrieval     Running
○ Re-ranking
○ Re-chunking
○ Query decomposition
```

After validation, the interface shows the improvement:

```text
                     BEFORE       AFTER
Context recall        0.41   →     0.86
Precision             0.83   →     0.81
Faithfulness          0.92   →     0.94
Overall               0.71   →     0.86

                 REPAIR SUCCESSFUL
```

---

## Quick start

### Backend-only offline demo

```bash
python -m venv .venv

# macOS/Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
python scripts/run_pipeline.py
pytest -q
```

The demo uses an offline TF-IDF/SVD vector store and requires no API key.

### API

From the backend project root:

```bash
PYTHONPATH=src python -m uvicorn ragguard.api.app:app --reload --port 8000
```

Routes:

- `GET /api/v1/health`
- `POST /api/v1/query`
- `POST /api/v1/evaluate`
- `POST /api/v1/detect`
- `POST /api/v1/repair`
- `POST /api/v1/narrate`
- `GET /api/v1/metrics`
- `GET /api/v1/failures`
- `GET /api/v1/repairs/{repair_id}`

### Frontend

```bash
cd frontend
npm install
npm run dev
```

The frontend runs on the Vite development server and connects to the API through `VITE_API_BASE_URL`.

### Docker Compose

```bash
docker compose up --build
```

---

## Design principles

1. Evaluation is explicit rather than hidden inside generation.
2. Failure modes are enumerated and testable.
3. Diagnosis maps failures to approved repairs.
4. Repair execution is policy-constrained.
5. Validation decides whether a repair is promoted.
6. LangGraph is an orchestration adapter, not the core domain.
7. The sequential runner keeps local demonstrations dependency-light.
8. The local vector store is replaceable.
9. Observability records technical evidence and audit information.
10. The NLP Narrator simplifies results without replacing technical evidence.
11. Destructive or broad repairs should support approval, rollback, and escalation.

---

## Repository structure

```text
ragguard/
├── backend/
│   ├── src/ragguard/
│   │   ├── ingestion/
│   │   ├── retrieval/
│   │   ├── evaluation/
│   │   ├── detection/
│   │   ├── diagnosis/
│   │   ├── repair/
│   │   ├── agents/
│   │   ├── observability/
│   │   ├── storage/
│   │   └── api/
│   ├── scripts/
│   └── tests/
├── frontend/
│   └── src/
│       ├── components/
│       ├── pages/
│       ├── api/
│       └── types/
├── data/
├── docs/
├── deployment/aws/
└── docker-compose.yml
```

---

## Production direction

The intended cloud topology is:

```text
S3 documents
     ↓
Ingestion workers
     ↓
RAGGuard API ─── Bedrock
     │
     ├── Managed vector store
     ├── Metadata store
     ├── LangGraph orchestration
     └── CloudWatch observability
```

Terraform under `deployment/aws/` is deliberately a starter layer. It is not a claim that an AWS environment has already been provisioned.

A production deployment should add:

- Authentication and role-based access control.
- Private networking and least-privilege IAM.
- Encrypted data and secret management.
- Durable workflow checkpoints.
- Immutable audit records.
- Repair approval and rollback controls.
- Index versioning and canary promotion.
- PII-safe telemetry.
- Load, security, and regression testing.

---

## Roadmap

- Connect the React Query Lab to the live API.
- Stream LangGraph or sequential-run node status to Live Runs.
- Add persistent failure and repair history.
- Add vector distribution and PCA/UMAP exploration.
- Add index-version comparison and drift alerts.
- Add Bedrock-backed NLP Narrator mode.
- Add managed vector-store adapters.
- Add production Terraform modules and security controls.

---

## License

See `LICENSE`.
