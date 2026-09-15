from fastapi.testclient import TestClient

from ragguard.api.app import app
from ragguard.api.runtime import workspace
from ragguard.common.exceptions import RetrievalError

client = TestClient(app)

def test_query_retrieval_error_returns_structured_http_response(monkeypatch):
    def failing_query(*args, **kwargs):
        raise RetrievalError("Retrieval failed.")

    monkeypatch.setattr(workspace, "query", failing_query)

    response = client.post(
        "/api/v1/query",
        json={
            "query": "How do I request a refund?",
            "top_k": 5,
            "method": "vector",
        },
    )

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "RETRIEVAL_ERROR",
            "message": "Retrieval failed.",
        }
    }
