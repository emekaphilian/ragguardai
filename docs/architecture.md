# Architecture

RAGGuard separates:

```text
INGEST
  ↓
RETRIEVE
  ↓
EVALUATE
  ↓
DETECT
  ↓
DIAGNOSE
  ↓
REPAIR
  ↓
VALIDATE
  ↓
OBSERVE
```

The vector store is an adapter. Core evaluation, detection, diagnosis and policy code do not depend on a specific vector database.

Agents are thin wrappers around those services.

## Reliability workflow orchestration

`ragguard.agents.graph.build_langgraph` coordinates the existing evaluator,
failure detector, diagnosis function, repair policy, repair engine, and
validator. Those modules own reliability decisions; graph nodes call them and
route their results. The workflow evaluates, detects, diagnoses, plans a
permitted repair, executes it, independently evaluates the candidate retrieval,
and promotes an improvement or restores the prior state. Failed repairs can
select another permitted strategy until the configured attempt limit; reaching
that limit ends in escalation. Policies may describe future strategies, but
the workflow only executes strategies with an implemented repair engine path.

The existing `POST /api/v1/repair` endpoint invokes this graph and accepts
`max_repair_attempts` (default 3, range 0–10). External observations remain an
evaluation and detection boundary; applying a repair to an external RAG system
requires a separate connector capable of performing and validating that change.

## Application integration contract

RAGGuard's required integration boundary is the versioned `RAGObservation`
contract in `ragguard.evaluation.live`. Each application owns a small adapter
that maps its framework-specific retrieval result to this stable payload.
RAGGuard consumes the query, application and environment, retrieved chunk IDs
and scores, retrieval method, embedding degradation signal, latency, and
optional answer. It does not require a particular provider, vector store, or
RAG framework. The external contract has no customer `tenant_id`; service
credentials map each registered application to RAGGuard's separate internal
tenant and storage namespace.

Applications can submit this payload to `POST /api/v1/observations`:

```json
{
  "contract_version": "v1",
  "source": {
    "application_id": "trustassist",
    "environment": "production"
  },
  "query": "How do I request a refund?",
  "retrieved_chunks": [
    {"id": "chunk-123", "score": 0.86},
    {"id": "chunk-456", "score": 0.79}
  ],
  "retrieval_method": "hybrid",
  "embedding_degraded": false,
  "retrieval_latency_ms": 82,
  "answer": "Refunds are available within 30 days."
}
```

The endpoint returns live evaluation signals and a failure event when a
configured signal crosses a threshold. Optional `metadata` is carried as
opaque context; core evaluation must not depend on application-specific keys.
Service credentials for this endpoint are set as server environment variables
and referenced by registered application records. They identify the authorized
application and RAGGuard tenant; the request body cannot select an internal
tenant.

### Optional adapter capabilities

Observation is the core integration and does not require an application to
expose its database, index, or query endpoint. Query Lab can optionally call a
registered HTTPS query adapter. Its v1 request is:

```json
{
  "contract_version": "v1",
  "query": "How do I request a refund?",
  "top_k": 5,
  "method": "hybrid"
}
```

The adapter responds with `contract_version`, `answer`, `retrieved_chunks`
(each containing an ID, score, and optionally text and source details),
`retrieval_method`, `retrieval_latency_ms`, and `embedding_degraded`. RAGGuard
evaluates that response using the same live evaluator as submitted
observations. Query, observation, health, and metadata are separate
capabilities: applications only expose the capabilities they support. The
current registration supports managed-index querying, external HTTPS querying,
and observation-only applications. Health and metadata probes are optional
future capabilities and are not required by this contract.

Query access does not authorize RAGGuard to change an external application.
Registered observation-only and external-query applications are monitored;
closed-loop recovery against them requires a separate repair adapter that can
apply and validate the application's own changes. TrustAssist is the reference
adapter for this contract, not a special case in RAGGuard's core.

## Tenant boundary

RAGGuard's workspace requests and agent state carry an immutable `TenantContext`. It contains
the tenant/application identity, authenticated user attributes, vector
namespace, policy version, and index version. Storage adapters must scope reads
and writes by `context.vector_namespace`; callers must not pass arbitrary tenant
IDs to retrieval functions.

Tenant policy selects the LLM provider and model. The provider factory supports
OpenAI, Anthropic, Cohere, and local Ollama, while business code consumes the
common provider contract. LangGraph remains an optional orchestration adapter
above these services rather than an application domain layer.

The current HTTP middleware accepts development headers (`X-RAGGuard-Tenant`,
`X-RAGGuard-User`, and `X-RAGGuard-Roles`) and resolves them against configured
tenant policies. Replace that transport parser with verified JWT or session
claims before a public deployment; the resolved `TenantContext` remains the
boundary used downstream.
