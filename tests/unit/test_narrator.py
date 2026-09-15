from ragguard.config import LLMSettings, Settings
from ragguard.narrator import generate_narration, narrate


def test_narrator_falls_back_when_llm_disabled():
    result = generate_narration(
        "Overview dashboard",
        {"metrics": {"context_recall": 0.87, "faithfulness": 0.82, "failure_rate": 0.12}},
        settings=Settings(llm=LLMSettings(enabled=False)),
    )

    assert result["title"].startswith("Overview dashboard")
    assert result["tone"] == "good"
    assert isinstance(result["bullets"], list)
    assert result["summary"]


def test_narrator_is_unavailable_without_live_metrics():
    assert generate_narration("Overview", {}, settings=Settings()) == {"available": False}


def test_narrator_validates_and_falls_back_on_invalid_llm_payload(monkeypatch):
    def fake_generate(*args, **kwargs):
        return {
            "title": "bad",
            "summary": "oops",
            "bullets": "not-a-list",
            "tone": "warn",
        }

    monkeypatch.setattr("ragguard.llm.client.generate_llm_narration", fake_generate)

    result = generate_narration(
        "Query Lab",
        {"metrics": {"context_recall": 0.61, "faithfulness": 0.74, "failure_rate": 0.25}},
        settings=Settings(llm=LLMSettings(enabled=True)),
    )

    assert result["title"].startswith("Query Lab")
    assert result["tone"] in {"good", "warn"}
    assert isinstance(result["bullets"], list)


def test_narrator_uses_fallback_provider(monkeypatch):
    calls = []

    class FailingProvider:
        def generate(self, prompt):
            calls.append("openai")
            raise RuntimeError("temporary provider failure")

    class WorkingProvider:
        def generate(self, prompt):
            calls.append("anthropic")
            return '{"title":"Query Lab","summary":"Healthy","bullets":["Looks good"],"tone":"good"}'

    providers = {"openai": FailingProvider(), "anthropic": WorkingProvider()}

    def get_provider(name, settings):
        return providers[name]

    monkeypatch.setattr("ragguard.llm.client.get_llm_provider", get_provider)

    result = generate_narration(
        "Query Lab",
        {"metrics": {"faithfulness": 0.9}},
        settings=Settings(llm=LLMSettings(
            enabled=True,
            provider="openai",
            fallback_providers=("anthropic",),
            api_key="test-key",
        )),
    )

    assert result["summary"] == "Healthy"
    assert calls == ["openai", "anthropic"]
