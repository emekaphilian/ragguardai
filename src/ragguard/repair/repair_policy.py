from ragguard.common.enums import RepairType


EXECUTABLE_REPAIRS = frozenset({
    RepairType.DEDUPLICATE,
    RepairType.HYBRID_RETRIEVAL,
    RepairType.RERANK,
})


def choose_repair(diagnosis, attempted=None):
    attempted = set(attempted or [])
    for repair in diagnosis.recommended_repairs:
        if repair not in attempted:
            return repair
    return None


def choose_executable_repair(diagnosis, attempted=None, available=None):
    attempted = set(attempted or [])
    permitted = EXECUTABLE_REPAIRS if available is None else EXECUTABLE_REPAIRS & set(available)
    for repair in diagnosis.recommended_repairs:
        if repair in permitted and repair not in attempted:
            return repair
    return None
