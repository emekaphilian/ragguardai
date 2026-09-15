from __future__ import annotations

from ragguard.llm.providers.base import LLMProvider


class CohereProvider(LLMProvider):
    def generate(self, prompt: str) -> str:
        try:
            from cohere import ClientV2
        except ImportError as exc:
            raise RuntimeError("Cohere SDK is not installed") from exc

        client = ClientV2(api_key=self.api_key, timeout=self.timeout)
        response = client.chat(model=self.model, messages=[{"role": "user", "content": prompt}])
        content = response.message.content[0].text if response.message.content else ""
        if not content:
            raise ValueError("Cohere returned an empty response")
        return content