from ragguard.common.enums import RepairType
from ragguard.repair.repair_policy import choose_repair

class Diagnosis:
    recommended_repairs = [RepairType.RECHUNK, RepairType.HYBRID_RETRIEVAL]

def test_policy_skips_attempted():
    assert choose_repair(Diagnosis(), [RepairType.RECHUNK]) == RepairType.HYBRID_RETRIEVAL
