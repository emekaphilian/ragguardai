from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from ragguard.common.enums import FailureMode, Severity
from ragguard.evaluation.live import LiveEvaluation, ObservationSource


class LiveFailureEvent(BaseModel):
    contract_version: Literal["v1"] = "v1"
    source: ObservationSource
    failure_id: str
    query: str
    failure_type: FailureMode
    severity: Severity
    evaluation: LiveEvaluation
    evidence: list[str] = Field(default_factory=list)
    metadata: dict[str, object] = Field(default_factory=dict)
