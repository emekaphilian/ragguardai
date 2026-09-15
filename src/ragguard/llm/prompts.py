import json
from typing import Any


def build_narration_prompt(page: str, data: dict[str, Any]) -> str:
    metrics = data.get("metrics", data)
    return f"""
You are a senior product analyst for a RAG system.
Write a short, plain-language summary for the page: {page}.

Use the metrics below and explain the system status in clear language for a non-technical stakeholder.
Return valid JSON only with this schema:
{{
  "title": "string",
  "summary": "string",
  "bullets": ["string", "string", "string"],
  "tone": "good" | "warn"
}}

Metrics:
{json.dumps(metrics, indent=2, default=str)}

Rules:
- Keep it brief and readable.
- Do not include markdown, code fences, or extra keys.
- Use more caution when failure metrics are elevated or retrieval quality is low.
- Ensure bullets are short strings.
"""
