from ragguard.agents.graph import run_sequential
from ragguard.agents.state import RAGGuardState
from ragguard.common.enums import RepairType
from ragguard.common.schemas import Chunk, EvaluationResult, RepairResult, ValidationResult
from ragguard.config import Thresholds
from ragguard.detection.failure_detector import FailureDetector
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.evaluation.evaluator import Evaluator
from ragguard.repair.repair_engine import RepairEngine
from ragguard.storage.vector_store import VectorStore


def test_deduplicate_repair_improves_labeled_retrieval_state():
    store = VectorStore()
    chunks = [
        Chunk(chunk_id="duplicate-1", document_id="noise-1", text="Refund request general information."),
        Chunk(chunk_id="duplicate-2", document_id="noise-2", text="Refund request general information."),
        Chunk(chunk_id="relevant", document_id="policy", text="Refunds are available within 30 days."),
    ]
    store.add(chunks)
    query = "refund request deadline"
    answer = "Refunds are available within 30 days."
    retrieval = store.search(query, top_k=2)
    evaluator = Evaluator()
    before = evaluator.evaluate(query, answer, retrieval, {"relevant"})
    state = RAGGuardState(query=query, retrieval_result=retrieval, evaluation_result=before)

    state = run_sequential(
        state, FailureDetector(Thresholds()), diagnose, RepairEngine(), store,
        evaluator, {"relevant"}, answer,
    )

    assert state.status == "repaired"
    assert state.repair_result.repair_type.value == "DEDUPLICATE"
    assert state.retrieval_result is state.repair_result.after_retrieval
    assert state.evaluation_result.overall_score > before.overall_score
    assert len({chunk.text for chunk in state.retrieval_result.documents}) == len(state.retrieval_result.documents)


class WorseRepairEngine:
    def execute(self, repair_type, store, query, before_metrics, relevant_ids, evaluator, answer, **kwargs):
        worse = EvaluationResult(
            context_precision=0.0, context_recall=0.0, faithfulness=0.0,
            answer_relevancy=0.0, citation_accuracy=0.0, overall_score=0.0,
        )
        return RepairResult(
            repair_id="worse", failure_id="", repair_type=repair_type,
            before_metrics=before_metrics, after_metrics=worse,
            improvement=worse.overall_score - before_metrics.overall_score,
            status="rejected", before_retrieval=kwargs["before_retrieval"],
            after_retrieval=kwargs["before_retrieval"],
        )

    def validate(self, result):
        return ValidationResult(valid=True, improved=False, score_delta=result.improvement, message="Worse")


def test_failed_repair_rolls_back_retrieval_state():
    store = VectorStore()
    chunks = [Chunk(chunk_id="noise", document_id="noise", text="Refund request information.")]
    store.add(chunks)
    retrieval = store.search("refund deadline", top_k=1)
    evaluator = Evaluator()
    before = evaluator.evaluate("refund deadline", "Refund deadline.", retrieval, {"relevant"})
    state = RAGGuardState(query="refund deadline", retrieval_result=retrieval, evaluation_result=before)

    state = run_sequential(
        state, FailureDetector(Thresholds()), diagnose, WorseRepairEngine(), store,
        evaluator, {"relevant"}, "Refund deadline.",
    )

    assert state.status == "rolled_back"
    assert state.retrieval_result is retrieval
    assert state.evaluation_result is before
