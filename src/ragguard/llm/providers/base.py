from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    def __init__(self, model: str, api_key: str, timeout: float = 15.0):
        self.model = model
        self.api_key = api_key
        self.timeout = timeout

    @abstractmethod
    def generate(self, prompt: str) -> str:
        """Generate a text response for the supplied prompt."""
