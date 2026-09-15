from fastapi.testclient import TestClient

from ragguard.api.app import app


client = TestClient(app)


def test_query_rejects_empty_query():
    response = client.post(
        "/api/v1/query",
        json={
            "query": "",
            "top_k": 5,
            "method": "hybrid",
        },
    )

    assert response.status_code == 422


def test_query_accepts_default_values():
    response = client.post(
        "/api/v1/query",
        json={
            "query": "How do I request a refund?",
        },
    )

    assert response.status_code != 422