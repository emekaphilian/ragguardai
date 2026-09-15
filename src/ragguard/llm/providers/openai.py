from __future__ import annotations

from ragguard.llm.providers.base import LLMProvider


class OpenAIProvider(LLMProvider):
    def generate(self, prompt: str) -> str:
        try:
            from openai import OpenAI
        except ImportError as exc:
            raise RuntimeError("OpenAI SDK is not installed") from exc

        client = OpenAI(api_key=self.api_key, timeout=self.timeout)
        response = client.chat.completions.create(
            model=self.model,
            temperature=0.2,
            messages=[{"role": "user", "content": prompt}],
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("OpenAI returned an empty response")
        return content