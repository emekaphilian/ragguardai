from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import httpx


@dataclass(frozen=True, slots=True)
class ObservationDelivery:
    """Outcome of a best-effort telemetry delivery."""

    delivered: bool
    status_code: int | None = None
    error: str | None = None


class RAGGuardObserver:
    """Send minimal RAG observations without affecting the application result.

    Query text is replaced with ``[redacted]`` by default. Answers, document
    text, and custom metadata are never included in the request. Network and
    HTTP errors are returned as a failed delivery rather than raised.
    """

    def __init__(
        self,
        *,
        base_url: str,
        application_id: str,
        environment: str,
        token: str,
        timeout_seconds: float = 1.0,
        include_query: bool = False,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        if self.base_url.endswith("/api/v1"):
            self.observation_url = f"{self.base_url}/observations"
        else:
            self.observation_url = f"{self.base_url}/api/v1/observations"
        self.application_id = application_id
        self.environment = environment
        self.token = token
        self.timeout_seconds = timeout_seconds
        self.include_query = include_query

    def observe(
        self,
        *,
        query: str,
        retrieved_chunks: Iterable[tuple[str, float]] = (),
        retrieval_method: str = "unknown",
        retrieval_latency_ms: float = 0,
        generation_status: str = "succeeded",
    ) -> ObservationDelivery:
        """Submit one observation; telemetry failures never escape this call."""
        payload = {
            "contract_version": "v1",
            "source": {
                "application_id": self.application_id,
                "environment": self.environment,
            },
            "query": query if self.include_query else "[redacted]",
            "retrieved_chunks": [
                {"id": chunk_id, "score": score}
                for chunk_id, score in retrieved_chunks
            ],
            "retrieval_method": retrieval_method,
            "retrieval_latency_ms": retrieval_latency_ms,
            "generation_status": generation_status,
        }
        try:
            response = httpx.post(
                self.observation_url,
                json=payload,
                headers={"Authorization": f"Bearer {self.token}"},
                timeout=self.timeout_seconds,
            )
        except httpx.HTTPError:
            return ObservationDelivery(delivered=False, error="RAGGuard is unavailable")

        if not response.is_success:
            return ObservationDelivery(
                delivered=False,
                status_code=response.status_code,
                error="RAGGuard rejected the observation",
            )
        return ObservationDelivery(delivered=True, status_code=response.status_code)
