import httpx

from ragguard.integrations.python_adapter import RAGGuardObserver


def observer(**overrides):
    options = {
        "base_url": "https://ragguard.example.test/api/v1/",
        "application_id": "biomedicalrag",
        "environment": "development",
        "token": "secret-token",
    }
    options.update(overrides)
    return RAGGuardObserver(**options)


def test_observer_redacts_query_and_sends_only_chunk_ids_and_scores(monkeypatch):
    captured = {}

    def post(url, **kwargs):
        captured.update(url=url, **kwargs)
        return httpx.Response(200, json={"evaluation": {"status": "HEALTHY"}})

    monkeypatch.setattr("ragguard.integrations.python_adapter.httpx.post", post)
    delivery = observer().observe(
        query="private biomedical question",
        retrieved_chunks=[("chunk-1", 0.9)],
        retrieval_method="hybrid",
        retrieval_latency_ms=18,
    )

    assert delivery.delivered is True
    assert captured["url"] == "https://ragguard.example.test/api/v1/observations"
    assert captured["headers"]["Authorization"] == "Bearer secret-token"
    assert captured["json"]["query"] == "[redacted]"
    assert captured["json"]["retrieved_chunks"] == [{"id": "chunk-1", "score": 0.9}]
    assert "private biomedical question" not in str(captured["json"])
    assert "answer" not in captured["json"]


def test_observer_fails_open_on_network_error(monkeypatch):
    monkeypatch.setattr(
        "ragguard.integrations.python_adapter.httpx.post",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(httpx.ConnectError("offline")),
    )
    delivery = observer().observe(query="query text")

    assert delivery.delivered is False
    assert delivery.error == "RAGGuard is unavailable"


def test_observer_can_explicitly_include_query(monkeypatch):
    captured = {}

    def post(_url, **kwargs):
        captured.update(kwargs)
        return httpx.Response(200)

    monkeypatch.setattr("ragguard.integrations.python_adapter.httpx.post", post)
    observer(include_query=True).observe(query="approved diagnostic query")

    assert captured["json"]["query"] == "approved diagnostic query"


def test_observer_reports_http_rejection_without_raising(monkeypatch):
    monkeypatch.setattr(
        "ragguard.integrations.python_adapter.httpx.post",
        lambda *_args, **_kwargs: httpx.Response(401),
    )

    delivery = observer().observe(query="query text")

    assert delivery.delivered is False
    assert delivery.status_code == 401
    assert delivery.error == "RAGGuard rejected the observation"
