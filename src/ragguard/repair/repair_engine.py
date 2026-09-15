from uuid import uuid4
from ragguard.common.schemas import RepairResult, ValidationResult
from ragguard.common.enums import RepairType
from .hybrid_retrieval import run_hybrid
from .reranking import rerank

class RepairEngine:
    def execute(self, repair_type, store, query, before_metrics, relevant_ids, evaluator, answer):
        if repair_type == RepairType.HYBRID_RETRIEVAL:
            retrieval = run_hybrid(store, query)
        elif repair_type == RepairType.RERANK:
            retrieval = rerank(query, store.search(query))
        else:
            retrieval = store.search(query)

        after = evaluator.evaluate(query, answer, retrieval, relevant_ids)
        improvement = after.overall_score - before_metrics.overall_score

        return RepairResult(
            repair_id=str(uuid4()),
            failure_id="",
            repair_type=repair_type,
            before_metrics=before_metrics,
            after_metrics=after,
            improvement=improvement,
            status="promoted" if improvement > 0 else "rejected",
        )

    def validate(self, result):
        return ValidationResult(
            valid=True,
            improved=result.improvement > 0,
            score_delta=result.improvement,
            message=(
                "Repair improved evaluation score."
                if result.improvement > 0
                else "Repair did not improve the score."
            ),
        )
