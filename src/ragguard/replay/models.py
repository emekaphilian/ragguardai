from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ReplayRequest(BaseModel):
    recovery_id: str = Field(min_length=1)
    mode: Literal["dry_run", "execute"] = "dry_run"


class ReplayResult(BaseModel):
    replay_id: str
    original_recovery_id: str
    mode: Literal["dry_run", "execute"]
    original_status: str
    replay_status: str
    original_score: float | None = None
    replay_score: float | None = None
    original_strategy: str | None = None
    replay_strategy: str | None = None
    regression_detected: bool
