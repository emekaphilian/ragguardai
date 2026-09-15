from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class NarrationResponse(BaseModel):
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)
    bullets: list[str] = Field(min_length=1, max_length=4)
    tone: Literal["good", "warn"]

    @field_validator("bullets")
    @classmethod
    def validate_bullets(cls, value: list[str]) -> list[str]:
        if not isinstance(value, list):
            raise TypeError("bullets must be a list of strings")
        if not all(isinstance(item, str) and item.strip() for item in value):
            raise ValueError("each bullet must be a non-empty string")
        return value
