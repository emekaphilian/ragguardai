# Connect a RAG application

Use this guide for any RAG application. The application name, framework, and
deployment host are supplied during setup; RAGGuard does not require an
application-specific code path.

## 1. Register the application

In RAGGuard, open **Connect Application**, choose the environment, and create a
setup plan. An administrator registers the application from the same page.
Registration creates an observation-only integration. It does not grant access
to the application's index, context, or repair operations.

The administrator credential is sent to RAGGuard for registration and is not
saved in the browser or given to the RAG application. The wizard returns a
separate application observation credential once. Store it in the application's
deployment secret manager as `RAGGUARD_OBSERVATION_TOKEN`; never put it in
source control, a client-side bundle, or a prompt.

## 2. Send one observation after a real RAG request

Instrument the server-side request path after retrieval and generation have
completed. Send one observation for that request to
`POST /api/v1/observations`. Use the observation credential as a bearer token.
Configure the API base URL and credential in the application host's secret or
environment settings:

```text
RAGGUARD_API_URL=https://ragguard.example.com/api/v1
RAGGUARD_OBSERVATION_TOKEN=<application observation credential>
```

The version 1 JSON contract is:

```json
{
  "contract_version": "v1",
  "source": {
    "application_id": "<registered application ID>",
    "environment": "<registered environment>"
  },
  "query": "<user query, subject to your privacy policy>",
  "retrieved_chunks": [],
  "retrieval_method": "<retriever or index name>",
  "retrieval_latency_ms": 0,
  "answer": "<generated answer, subject to your privacy policy>",
  "metadata": {}
}
```

Populate `retrieved_chunks` with the chunk identifiers and scores available to
your integration. Do not send document or chunk text by default. Keep query and
answer collection aligned with the application's data handling policy. Send the
observation from a trusted server process, not directly from a browser.

Instrument the application's normal request path so it remains the source of
truth. A successful HTTP response to the observation request means RAGGuard
accepted that event; it does not mean the RAG answer was safe or correct. Keep
monitoring fail-open if your application must continue serving when RAGGuard is
unavailable, and record telemetry delivery failures in the application's own
logs or metrics.

## 3. Verify monitoring

Return to **Connect Application** and refresh the application status after the
instrumented application has served a real request. RAGGuard reports connected
only after it receives and evaluates an observation for the registered
application and environment. The page shows the latest observation and
evaluation status. A setup plan or a credential by itself does not count as a
verified connection.

If status remains waiting for data, check that the source application is using
the exact registered application ID and environment, that its observation
credential is current, and that it posts to the RAGGuard API base URL. Rotate a
credential from the wizard if it was lost; rotation invalidates its previous
value, which must then be replaced in the source application's secret manager.

## 4. Configure a constrained remote repair adapter (optional)

Observation-only registration leaves repair, context access, and independent
verification disabled. For an `observation_only` or `external_rag_api` registration, remote repair
requires both `repair_endpoint_url` and `repair_token_env_var`. The latter is
only an environment-variable **name** stored in the registration; set its
secret value in the RAGGuard server environment. Do not reuse the query or
observation credential.

The application owner must separately enable `repair_authorized` through the
administrator capabilities API. Without that explicit authorization,
RAGGuard does not request a repair. Remote repair does not grant RAGGuard
access to the application's index or context: the application keeps context
local and validates its own repair operation.

The repair endpoint is a server-to-server HTTPS endpoint. RAGGuard requires
its DNS name to resolve only to public IP addresses, does not follow redirects,
and limits response bodies. The adapter contract is v1:

* `GET {repair_endpoint_url}/capabilities` returns the operations the
  application implements. BiomedicalRag currently advertises only
  `HYBRID_RETRIEVAL` and `RERANK`; it rejects `DEDUPLICATE`. RAGGuard intersects
  this list with its diagnosis and executable repair strategies.
* `POST {repair_endpoint_url}` receives a bearer token and a request body like:

  ```json
  {
    "contract_version": "v1",
    "request_id": "source-request-id",
    "application_id": "biomedicalrag",
    "environment": "production",
    "query": "[redacted]",
    "failure_type": "NO_RETRIEVAL",
    "strategy": "RERANK",
    "retrieved_chunks": [{"id": "chunk-1", "score": 0.42}]
  }
  ```

  The `Idempotency-Key` header carries the same request ID. When the source
  observation has no request ID, RAGGuard generates one. The request never
  includes answer text, chunk/document text, arbitrary code, or a free-form
  repair instruction.
* BiomedicalRag correlates `request_id` to a short-lived in-process request
  context. It ignores the request query and chunk list, so query and source text
  stay inside BiomedicalRag. Supported repairs rerun the pending query through
  its existing safety and validation pipeline. A candidate is returned to the
  user only when local context and answer checks pass and its validation score
  improves; otherwise the original answer is retained. This is a request-scoped
  adjustment and does not rewrite the index or persistent retrieval settings.
* The adapter returns a contract-v1 result containing the same `request_id`
  and `strategy`, `status` (`promoted`, `rejected`, or `rolled_back`),
  `validated`, `context_verified`, and optional numeric `improvement`. A
  `promoted` result must have both validation fields set to `true`. The
  application records authorization and outcome metadata without recording
  query, answer, or source text. RAGGuard issues at most one repair request per
  failed observation.

The capabilities and repair endpoints both require the separate repair
credential as a bearer token. A missing credential, failed adapter request, or
invalid response is recorded as unavailable/escalated and does not grant
additional access. BiomedicalRag exposes only authenticated internal repair
endpoints when `RAGGUARD_REPAIR_TOKEN` is configured. Set that token on both
servers in separate secret settings with the same value; keep it out of browser
configuration and source control. BiomedicalRag also needs server-side
`RAGGUARD_URL`, `RAGGUARD_APPLICATION_ID=biomedicalrag`,
`RAGGUARD_ENVIRONMENT`, and `RAGGUARD_OBSERVATION_TOKEN` values. Keep
authorization disabled until registration and server credentials are configured.

## Framework adapters

The observation contract is framework-neutral. Put framework-specific event
mapping at the application boundary: map the framework's completed retrieval
and generation event into the contract above, then send it using the server-side
observation credential. This keeps the RAGGuard API and core independent of
LangChain, LlamaIndex, Haystack, or a custom pipeline. Use a framework adapter
when one is available for your stack; otherwise the same contract can be sent
from the application's existing retrieval callback or request handler.
