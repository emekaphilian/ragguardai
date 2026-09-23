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


def test_repair_route_uses_repair_engine_validation():
    response = client.post(
        "/api/v1/repair",
        json={
            "query": "How do I request a refund?",
            "answer": "Refunds are available within 30 days of purchase.",
            "relevant_chunk_ids": ["refund:0"],
        },
    )

    assert response.status_code == 200

    body = response.json()
    assert "status" in body
    assert "repair_type" in body
    assert "before_metrics" in body
    assert "after_metrics" in body
    assert "improvement" in body
    assert "validated" in body
    assert "retrieval" in body


def test_detect_route_uses_failure_detector():
    response = client.post(
        "/api/v1/detect",
        json={
            "query": "refund deadline",
            "metrics": {
                "context_precision": 0.1,
                "context_recall": 0.1,
                "faithfulness": 0.9,
                "answer_relevancy": 0.9,
                "citation_accuracy": 0.1,
                "overall_score": 0.42,
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["failure_detected"] is True
    assert response.json()["failure_type"] == "LOW_CONTEXT_RECALL"
