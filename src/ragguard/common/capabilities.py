from __future__ import annotations

from typing import Literal, TypedDict


AuthorizationStatus = Literal["authorized", "not_authorized", "not_applicable"]


class CapabilityStateData(TypedDict):
    authorization: AuthorizationStatus
    performed: bool
    reason: str | None


class CapabilityExecutionData(TypedDict):
    context_verification: CapabilityStateData
    independent_verification: CapabilityStateData
    repair: CapabilityStateData


def capability_state(
    authorization: AuthorizationStatus,
    *,
    performed: bool,
    reason: str | None = None,
) -> CapabilityStateData:
    return {
        "authorization": authorization,
        "performed": performed,
        "reason": reason,
    }


def capability_execution(
    *,
    context_verification: CapabilityStateData,
    independent_verification: CapabilityStateData,
    repair: CapabilityStateData,
) -> CapabilityExecutionData:
    return {
        "context_verification": context_verification,
        "independent_verification": independent_verification,
        "repair": repair,
    }
