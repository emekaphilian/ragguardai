from __future__ import annotations

import json
import ipaddress
import os
import socket
from statistics import fmean

import httpx
from fastapi import HTTPException

from ragguard.api.schemas import ExternalRAGQueryResponse
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.evaluation.live import ObservationSource, RAGObservation, RetrievedChunkObservation
from ragguard.evaluation.live_evaluator import LiveEvaluator
from ragguard.evaluation.metrics import answer_relevancy
from ragguard.tenants.application_registration import ApplicationRegistration

MAX_ADAPTER_RESPONSE_BYTES = 1_000_000


def _validate_public_endpoint(url: str) -> None:
    try:
        parsed = httpx.URL(url)
        host = parsed.host
        port = parsed.port or 443
        addresses = {
            ipaddress.ip_address(result[4][0])
            for result in socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
        }
    except (ValueError, socket.gaierror) as exc:
        raise HTTPException(status_code=502, detail="External query adapter host could not be resolved safely.") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise HTTPException(status_code=403, detail="External query adapters must resolve only to public IP addresses.")


def query_external_application(
    application: ApplicationRegistration,
    *,
    query: str,
    top_k: int,
    method: str,
) -> dict:
    if not application.query_endpoint_url:
        raise HTTPException(status_code=409, detail="Application has no query adapter endpoint.")
    _validate_public_endpoint(application.query_endpoint_url)

    headers = {"Content-Type": "application/json"}
    if application.query_token_env_var:
        token = os.getenv(application.query_token_env_var)
        if not token:
            raise HTTPException(
                status_code=503,
                detail="The external application credential is not configured on the server.",
            )
        headers["Authorization"] = f"Bearer {token}"

    try:
        with httpx.Client(timeout=10.0, follow_redirects=False, trust_env=False) as client:
            with client.stream(
                "POST",
                application.query_endpoint_url,
                headers=headers,
                json={
                    "contract_version": "v1",
                    "query": query,
                    "top_k": top_k,
                    "method": method,
                },
            ) as response:
                if response.is_redirect:
                    raise HTTPException(status_code=502, detail="External query adapter redirects are not supported.")
                response.raise_for_status()
                body = bytearray()
                for part in response.iter_bytes():
                    body.extend(part)
                    if len(body) > MAX_ADAPTER_RESPONSE_BYTES:
                        raise HTTPException(status_code=502, detail="External query response exceeded the size limit.")
    except HTTPException:
        raise
    except httpx.TimeoutException as exc:
        raise HTTPException(status_code=504, detail="External query adapter timed out.") from exc
    except httpx.HTTPStatusError as exc:
        raise HTTPException(status_code=502, detail="External query adapter returned an error.") from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail="External query adapter is unavailable.") from exc

    try:
        adapter_result = ExternalRAGQueryResponse.model_validate(json.loads(body))
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=502, detail="External query response did not match the RAGGuard adapter contract v1.") from exc

    observation = RAGObservation(
        contract_version="v1",
        source=ObservationSource(
            application_id=application.application_id,
            environment=application.environment,
        ),
        query=query,
        retrieved_chunks=[
            RetrievedChunkObservation(id=chunk.id, score=chunk.score)
            for chunk in adapter_result.retrieved_chunks
        ],
        retrieval_method=adapter_result.retrieval_method,
        embedding_degraded=adapter_result.embedding_degraded,
        retrieval_latency_ms=adapter_result.retrieval_latency_ms,
        answer=adapter_result.answer,
    )
    evaluation = LiveEvaluator().evaluate(observation)
    failure = LiveFailureDetector().detect(observation, evaluation)
    texts = [chunk.text for chunk in adapter_result.retrieved_chunks if chunk.text]
    context = " ".join(texts)
    answer_terms = [term for term in adapter_result.answer.lower().split() if len(term) > 3]
    quality = {
        "term_match": fmean(chunk.score for chunk in adapter_result.retrieved_chunks)
        if adapter_result.retrieved_chunks
        else 0.0,
        "source_coverage": None,
        "answer_relevancy": answer_relevancy(query, adapter_result.answer),
        "faithfulness": (
            sum(term in context.lower() for term in answer_terms) / max(1, len(answer_terms))
            if texts and adapter_result.answer
            else None
        ),
    }
    return {
        "answer": adapter_result.answer,
        "rag_status": "retrieved" if adapter_result.retrieved_chunks else "no_match",
        "retrieval_quality": quality,
        "retrieval_method": adapter_result.retrieval_method,
        "latency_ms": adapter_result.retrieval_latency_ms,
        "sources": [
            {
                "chunk_id": chunk.id,
                "document_id": chunk.document_id or chunk.id,
                "source": chunk.source or application.display_name,
                "section": chunk.section,
                "text": chunk.text,
                "score": chunk.score,
            }
            for chunk in adapter_result.retrieved_chunks
        ],
        "reliability_evaluation": evaluation.model_dump(mode="json"),
        "reliability_failure": failure.model_dump(mode="json") if failure else None,
        "application_id": application.application_id,
        "environment": application.environment,
        "knowledge_source": application.knowledge_source,
    }
