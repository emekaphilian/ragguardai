from __future__ import annotations

import re
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter()


class IntegrationMethod(BaseModel):
    id: str
    label: str
    kind: Literal["framework", "python", "api", "managed"]
    best_for: str
    technical_level: Literal["minimal", "moderate", "advanced"]
    summary: str
    instructions: list[str]


class IntegrationPlanRequest(BaseModel):
    application_name: str = Field(min_length=1, max_length=160)
    framework: str = "custom"
    environment: str = "development"
    knowledge_source: Literal["managed_index", "external_rag_api", "observation_only"] = "observation_only"
    integration_method: str | None = None


INTEGRATION_METHODS = [
    IntegrationMethod(
        id="python-adapter",
        label="Python integration package",
        kind="python",
        best_for="Python RAG applications and custom orchestration pipelines",
        technical_level="moderate",
        summary="Use the included Python observer at the point where your app has retrieval metrics. Query text is redacted by default; answers and document text are not sent.",
        instructions=[
            "Keep your existing index and retrieval system; observation monitoring does not require moving documents to RAGGuard.",
            "Ask a RAGGuard workspace administrator to register the app and provision its observation credential. This wizard does not generate credentials yet.",
            "A developer must add the included Python observer where the app already has retrieved chunk IDs, scores, and retrieval latency. Delivery failures do not interrupt the app's answer.",
            "Return here and check the connection after the app sends an observation. The BiomedicalRag source project is not present in this workspace, so RAGGuard cannot name its exact source file yet.",
        ],
    ),
    IntegrationMethod(
        id="langchain",
        label="LangChain integration",
        kind="framework",
        best_for="LangChain or LangGraph-based applications that already structure retrieval and generation",
        technical_level="moderate",
        summary="Wrap the existing chain or graph so RAGGuard receives retrieval quality, latency, and failure outcomes without rewriting the app.",
        instructions=[
            "Identify the retrieval and generation nodes in your LangChain chain.",
            "Register the chain as a monitored application in RAGGuard.",
            "Attach the observation callback or middleware to the chain runtime.",
            "Validate a live response before enabling automated repair.",
        ],
    ),
    IntegrationMethod(
        id="custom-api",
        label="Custom API integration",
        kind="api",
        best_for="Existing applications without a supported framework-specific adapter",
        technical_level="advanced",
        summary="Use the RAGGuard observation contract and a service-side adapter to send only operational telemetry and evaluation signals.",
        instructions=[
            "Expose a single outbound observation endpoint for your application.",
            "Map retrieval success, latency, and failure stage into the observation schema.",
            "Store the credential in your deployment environment, not in source control.",
            "Test the payload with the built-in connection check before production monitoring.",
        ],
    ),
    IntegrationMethod(
        id="managed-index",
        label="Managed index + registry",
        kind="managed",
        best_for="Applications that rely on a managed vector index and need RAGGuard to monitor evaluation outcomes",
        technical_level="minimal",
        summary="Register the managed index and enable observation-based monitoring while keeping retrieval logic in the existing RAGGuard-managed index.",
        instructions=[
            "Register the application in the tenant registry.",
            "Provide the managed vector namespace and observation credential.",
            "Activate monitoring for the chosen environment.",
            "Check the application dashboard before granting repair authorization.",
        ],
    ),
]


@router.get("/integration-methods")
def list_integration_methods() -> list[dict[str, object]]:
    return [method.model_dump() for method in INTEGRATION_METHODS]


@router.post("/application-integration")
def build_application_integration(request: IntegrationPlanRequest) -> dict[str, object]:
    selected = next(
        (method for method in INTEGRATION_METHODS if method.id == request.integration_method),
        next(
            (
                method for method in INTEGRATION_METHODS
                if request.framework.lower() in {"python", "langchain", "llamaindex"}
                and method.id == "python-adapter"
            ),
            INTEGRATION_METHODS[0],
        ),
    )

    checklist = [
        "Registration: not completed by this setup plan.",
        "Credential: not generated by this setup plan; configure it through your deployment's secure secret settings.",
        "Monitoring: not active until your application sends an observation.",
        "Connection: not verified until RAGGuard receives and evaluates an observation.",
    ]

    if request.knowledge_source == "managed_index":
        checklist.insert(1, "RAGGuard-managed index: configure a namespace only if RAGGuard will manage retrieval for this app.")
    elif request.knowledge_source == "external_rag_api":
        checklist.insert(1, "External RAG API: the app keeps its own index; provide an HTTPS query endpoint only if RAGGuard should query it.")
    else:
        checklist.insert(1, "External RAG application: keep your current retrieval system; no index migration or RAGGuard query access is needed for monitoring.")

    suggested_application_id = re.sub(
        r"[^A-Za-z0-9._-]+", "-", request.application_name.strip()
    ).strip("-.")[:100] or "rag-application"
    if not suggested_application_id[0].isalnum():
        suggested_application_id = f"app-{suggested_application_id}"[:100]
    python_example = None
    if selected.id == "python-adapter":
        python_example = (
            "import os\n"
            "from ragguard.integrations import RAGGuardObserver\n\n"
            "observer = RAGGuardObserver(\n"
            "    base_url=os.environ['RAGGUARD_URL'],\n"
            f"    application_id={suggested_application_id!r},\n"
            f"    environment={request.environment!r},\n"
            "    token=os.environ['RAGGUARD_OBSERVATION_TOKEN'],\n"
            ")\n\n"
            "# Call after retrieval; pass chunk IDs and scores, never document text.\n"
            "observer.observe(\n"
            "    query=query,  # redacted before sending by default\n"
            "    retrieved_chunks=[(chunk.id, chunk.score) for chunk in chunks],\n"
            "    retrieval_method='hybrid',\n"
            "    retrieval_latency_ms=retrieval_latency_ms,\n"
            ")"
        )

    return {
        "application_name": request.application_name,
        "suggested_application_id": suggested_application_id,
        "environment": request.environment,
        "framework": request.framework,
        "knowledge_source": request.knowledge_source,
        "recommended_method": selected.model_dump(),
        "checklist": checklist,
        "security_notes": [
            "Observation credentials are scoped to one application and one environment.",
            "Monitoring does not implicitly grant repair permission.",
            "Registration alone is not proof that telemetry is arriving.",
        ],
        # This endpoint only prepares guidance. It does not register the app,
        # issue a credential, or verify delivery of an observation.
        "status": "setup_guidance_only",
        "next_steps": selected.instructions,
        "python_example": python_example,
    }
