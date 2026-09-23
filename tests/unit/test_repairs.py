from ragguard.common.enums import RepairType, RetrievalMethod
from ragguard.common.schemas import Chunk, EvaluationResult, RepairResult, RetrievalResult
from ragguard.repair.repair_policy import choose_repair
from ragguard.repair.repair_engine import RepairEngine
from ragguard.repair.deduplicate import deduplicate, retrieval_stats

class Diagnosis:
    recommended_repairs = [RepairType.RECHUNK, RepairType.HYBRID_RETRIEVAL]

def test_policy_skips_attempted():
    assert choose_repair(Diagnosis(), [RepairType.RECHUNK]) == RepairType.HYBRID_RETRIEVAL


def test_deduplicate_removes_duplicate_chunks():
    retrieval = RetrievalResult(
        query="refund policy",
        documents=[
            Chunk(chunk_id="c1", document_id="d1", text="Refunds are available within 30 days."),
            Chunk(chunk_id="c2", document_id="d1", text="Refunds are available within 30 days."),
            Chunk(chunk_id="c3", document_id="d2", text="Contact support for merchant refunds."),
        ],
        scores=[0.91, 0.90, 0.76],
        retrieval_method=RetrievalMethod.VECTOR,
    )

    deduped = deduplicate(retrieval)

    assert [chunk.chunk_id for chunk in deduped.documents] == ["c1", "c3"]
    assert len(deduped.scores) == 2
    assert retrieval_stats(retrieval) == {
        "retrieved_chunks": 3, "unique_chunks": 2, "duplicate_chunks": 1,
    }


def test_repair_engine_validation_detects_improvement():
    engine = RepairEngine()
    result = RepairResult(
        repair_id="repair-1",
        failure_id="failure-1",
        repair_type=RepairType.DEDUPLICATE,
        before_metrics=EvaluationResult(
            context_precision=0.40,
            context_recall=0.80,
            faithfulness=0.70,
            answer_relevancy=0.90,
            overall_score=0.72,
        ),
        after_metrics=EvaluationResult(
            context_precision=0.80,
            context_recall=0.80,
            faithfulness=0.70,
            answer_relevancy=0.90,
            overall_score=0.80,
        ),
        improvement=0.08,
        status="promoted",
    )

    validation = engine.validate(result)

    assert validation.valid is True
    assert validation.improved is True
    assert validation.score_delta == 0.08


def test_repair_engine_validation_detects_no_improvement():
    engine = RepairEngine()
    metrics = EvaluationResult(
        context_precision=0.4, context_recall=0.8, faithfulness=0.7,
        answer_relevancy=0.9, overall_score=0.7,
    )
    result = RepairResult(
        repair_id="repair-2", failure_id="failure-2", repair_type=RepairType.DEDUPLICATE,
        before_metrics=metrics, after_metrics=metrics, improvement=0.0, status="rejected",
    )

    validation = engine.validate(result)

    assert validation.valid is True
    assert validation.improved is False
    assert validation.score_delta == 0.0
