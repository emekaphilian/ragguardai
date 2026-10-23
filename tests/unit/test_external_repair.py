import json

import pytest

from ragguard.api import external_repair
from ragguard.common.enums import RepairType
from ragguard.evaluation.live import RAGObservation
from ragguard.tenants.application_registration import ApplicationRegistration


class FakeResponse:
    is_redirect = False

    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def raise_for_status(self):
        return None

    def iter_bytes(self):
        yield self.payload


class FakeClient:
    calls = []

    def __init__(self, **kwargs):
        self.options = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_):
        return False

    def stream(self, method, url, *, headers, json=None):
        self.calls.append((method, url, headers, json, self.options))
        if method == "GET":
            return FakeResponse({
                "contract_version": "v1",
                "supported_repairs": ["RERANK", "REINDEX"],
            })
        return FakeResponse({
            "contract_version": "v1",
            "request_id": json["request_id"],
            "strategy": json["strategy"],
            "status": "promoted",
            "validated": True,
            "context_verified": True,
            "improvement": 0.1,
        })


def test_remote_repair_uses_separate_secret_and_minimal_allowlisted_payload(
    monkeypatch,
):
    FakeClient.calls.clear()
    monkeypatch.setattr(external_repair.httpx, "Client", FakeClient)
    monkeypatch.setattr(external_repair, "_validate_public_endpoint", lambda _url: None)
    monkeypatch.setenv("REMOTE_REPAIR_SECRET", "repair-secret")
    application = ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="biomedicalrag",
        display_name="BiomedicalRag",
        environment="production",
        knowledge_source="external_rag_api",
        repair_endpoint_url="https://biomedical.example.test/repair",
        repair_token_env_var="REMOTE_REPAIR_SECRET",
        repair_authorized=True,
    )
    observation = RAGObservation.model_validate({
        "contract_version": "v1",
        "source": {
            "application_id": "biomedicalrag",
            "environment": "production",
        },
        "query": "private query",
        "request_id": "request-123",
        "retrieved_chunks": [
            {"id": "chunk-1", "score": 0.7},
        ],
        "answer": "private answer",
    })

    supported = external_repair.get_supported_repairs(application)
    result = external_repair.request_external_repair(
        application,
        observation,
        failure_type="NO_RETRIEVAL",
        strategy=RepairType.RERANK,
    )

    assert supported == {RepairType.RERANK}
    assert result.status == "promoted"
    capability_call, repair_call = FakeClient.calls
    assert capability_call[0] == "GET"
    assert capability_call[2]["Authorization"] == "Bearer repair-secret"
    assert repair_call[0] == "POST"
    assert repair_call[2]["Idempotency-Key"] == "request-123"
    assert repair_call[3]["strategy"] == "RERANK"
    assert repair_call[3]["retrieved_chunks"] == [{"id": "chunk-1", "score": 0.7}]
    assert "answer" not in repair_call[3]
    assert "private answer" not in json.dumps(repair_call[3])
    assert "private query" in json.dumps(repair_call[3])
    assert repair_call[4]["follow_redirects"] is False
    assert repair_call[4]["trust_env"] is False


def test_remote_repair_rejects_unimplemented_strategy(monkeypatch):
    application = ApplicationRegistration(
        ragguard_tenant_id="tenant-a",
        application_id="biomedicalrag",
        display_name="BiomedicalRag",
        environment="production",
        knowledge_source="external_rag_api",
        repair_endpoint_url="https://biomedical.example.test/repair",
        repair_token_env_var="REMOTE_REPAIR_SECRET",
        repair_authorized=True,
    )
    with pytest.raises(external_repair.ExternalRepairError):
        external_repair.request_external_repair(
            application,
            RAGObservation.model_validate({
                "contract_version": "v1",
                "source": {
                    "application_id": "biomedicalrag",
                    "environment": "production",
                },
                "query": "query",
            }),
            failure_type="NO_RETRIEVAL",
            strategy=RepairType.REINDEX,
        )
