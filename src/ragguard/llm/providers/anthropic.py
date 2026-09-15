from __future__ import annotations

from ragguard.llm.providers.base import LLMProvider


class AnthropicProvider(LLMProvider):
    def generate(self, prompt: str) -> str:
        try:
            from anthropic import Anthropic
        except ImportError as exc:
            raise RuntimeError("Anthropic SDK is not installed") from exc

        client = Anthropic(api_key=self.api_key, timeout=self.timeout)
        response = client.messages.create(
            model=self.model,
            max_tokens=600,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        content = "".join(block.text for block in response.content if hasattr(block, "text"))
        if not content:
            raise ValueError("Anthropic returned an empty response")
        return content