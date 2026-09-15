from __future__ import annotations

import json
from urllib.request import Request, urlopen

from ragguard.llm.providers.base import LLMProvider


class OllamaProvider(LLMProvider):
    """Ollama's local API provider. API keys are not required by default."""

    def generate(self, prompt: str) -> str:
        request = Request(
            "http://localhost:11434/api/generate",
            data=json.dumps({"model": self.model, "prompt": prompt, "stream": False}).encode(),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=self.timeout) as response:  # nosec B310 - fixed local URL
            return json.loads(response.read())["response"]
