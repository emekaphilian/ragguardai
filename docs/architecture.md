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

## Tenant boundary

Every request and agent state carries an immutable `TenantContext`. It contains
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
