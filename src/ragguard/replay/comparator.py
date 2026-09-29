from __future__ import annotations

from uuid import uuid4

from ragguard.observability.recovery_audit import RecoveryAuditRecord
from ragguard.replay.models import ReplayResult


def _strategy(attempts: list[dict], *, promoted: bool) -> str | None:
    if promoted:
        selected = next(
            (attempt for attempt in attempts if attempt.get("status") == "promoted"),
            None,
        )
        if selected is not None:
            return selected.get("strategy")
    return attempts[-1].get("strategy") if attempts else None


def compare_replay(
    original: RecoveryAuditRecord,
    replay_state: dict,
    *,
    mode: str,
) -> ReplayResult:
    replay_audit = replay_state.get("recovery_audit")
    replay_attempts = replay_audit.attempts if replay_audit is not None else []
    replay_status = replay_state.get("status", "unknown")

    original_score = (
        original.final_score
        if original.final_score is not None
        else original.original_score
    )
    replay_score = None
    if replay_audit is not None:
        replay_score = (
            replay_audit.final_score
            if replay_audit.final_score is not None
            else replay_audit.original_score
        )

    regression = (
        original_score is not None
        and replay_score is not None
        and replay_score < original_score
    )

    return ReplayResult(
        replay_id=str(uuid4()),
        original_recovery_id=original.recovery_id,
        mode=mode,
        original_status=original.final_status,
        replay_status=replay_status,
        original_score=original_score,
        replay_score=replay_score,
        original_strategy=_strategy(
            original.attempts,
            promoted=original.final_status == "promoted",
        ),
        replay_strategy=_strategy(
            replay_attempts,
            promoted=replay_status in {"promoted", "repaired"},
        ),
        regression_detected=bool(regression),
    )
