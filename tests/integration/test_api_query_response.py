from fastapi.testclient import TestClient

from ragguard.api.app import app

client = TestClient(app)


def test_query_returns_stable_response_contract():
    response = client.post(
        "/api/v1/query",
        json={
            "query": "How do I request a refund?",
            "top_k": 5,
            "method": "hybrid",
        },
    )

    assert response.status_code == 200

    body = response.json()

    assert "answer" in body
    assert "rag_status" in body
    assert "retrieval_quality" in body
    assert "sources" in body
    assert "retrieval_method" in body
    assert "latency_ms" in body

    assert isinstance(body["answer"], str)
    assert isinstance(body["retrieval_quality"], dict)
    assert isinstance(body["sources"], list)
    assert isinstance(body["latency_ms"], (int, float))