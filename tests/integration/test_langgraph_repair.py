from ragguard.agents.graph import build_langgraph
from ragguard.agents.state import RAGGuardState
from ragguard.common.enums import (
    FailureMode,
    RepairType,
    RetrievalMethod,
    Severity,
)
from ragguard.common.schemas import (
    Chunk,
    EvaluationResult,
    FailureEvent,
    RepairResult,
    RetrievalResult,
    ValidationResult,
)
from ragguard.config import Thresholds, load_settings
from ragguard.detection.failure_detector import FailureDetector
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.evaluation.evaluator import Evaluator
from ragguard.repair.repair_engine import RepairEngine
from ragguard.storage.vector_store import VectorStore


def build_duplicate_graph(repair_engine=None):
    store = VectorStore()
    store.add([
        Chunk(
            chunk_id="duplicate-1",
            document_id="noise-1",
            text="Refund request general information.",
        ),
        Chunk(
            chunk_id="duplicate-2",
            document_id="noise-2",
            text="Refund request general information.",
        ),
        Chunk(
            chunk_id="relevant",
            document_id="policy",
            text="Refunds are available within 30 days.",
        ),
    ])
    query = "refund request deadline"
    answer = "Refunds are available within 30 days."
    evaluator = Evaluator()
    state = RAGGuardState(
        query=query,
        retrieval_result=store.search(query, top_k=3),
    )
    graph = build_langgraph(
        FailureDetector(Thresholds()),
        diagnose,
        repair_engine or RepairEngine(),
        store,
        evaluator,
        {"relevant"},
        answer,
    )
    return graph, state


def test_langgraph_healthy_retrieval_ends_without_repair():
    store = VectorStore()
    store.add([
        Chunk(
            chunk_id="relevant",
            document_id="policy",
            text="Refund policy: refunds are available within 30 days.",
        ),
    ])
    query = "refund policy"
    answer = "refund policy"
    state = RAGGuardState(
        query=query,
        retrieval_result=store.search(query, top_k=1),
    )
    graph = build_langgraph(
        FailureDetector(Thresholds()),
        diagnose,
        RepairEngine(),
        store,
        Evaluator(),
        {"relevant"},
        answer,
    )

    result = graph.invoke(state)

    assert result["status"] == "healthy"
    assert result["failure_event"] is None
    assert result["diagnosis"] is None
    assert result["repair_result"] is None


def test_langgraph_deduplicates_and_promotes_improved_retrieval():
    graph, state = build_duplicate_graph()

    result = graph.invoke(state)

    assert result["status"] == "promoted"
    assert result["failure_event"].failure_type.value == "DUPLICATE_CONTEXT"
    assert result["repair_result"].repair_type == RepairType.DEDUPLICATE
    assert result["validation_result"].improved is True
    assert (
        result["repair_result"].after_metrics.overall_score
        > result["repair_result"].before_metrics.overall_score
    )
    assert result["retrieval_result"] is result["repair_result"].after_retrieval
    assert len({chunk.text for chunk in result["retrieval_result"].documents}) == len(
        result["retrieval_result"].documents
    )


class WorseRepairEngine:
    def execute(
        self,
        repair_type,
        store,
        query,
        before_metrics,
        relevant_ids,
        evaluator,
        answer,
        **kwargs,
    ):
        worse_retrieval = kwargs["before_retrieval"].model_copy(
            update={"documents": [], "scores": []}
        )
        return RepairResult(
            repair_id="worse",
            failure_id="",
            repair_type=repair_type,
            before_metrics=before_metrics,
            after_metrics=before_metrics,
            improvement=0.0,
            status="rejected",
            before_retrieval=kwargs["before_retrieval"],
            after_retrieval=worse_retrieval,
        )

    def validate(self, result):
        return ValidationResult(
            valid=True,
            improved=False,
            score_delta=result.improvement,
            message="Repair made the evaluation worse.",
        )


class LowRecallDetector:
    def detect(self, query, metrics, retrieval):
        return FailureEvent(
            failure_id="low-recall",
            query=query,
            failure_type=FailureMode.LOW_CONTEXT_RECALL,
            severity=Severity.MEDIUM,
            metrics=metrics,
        )


class FailHybridThenRerankEngine:
    def __init__(self):
        self.engine = RepairEngine()
        self.attempts = []
        self.before_retrievals = []

    def execute(
        self,
        repair_type,
        store,
        query,
        before_metrics,
        relevant_ids,
        evaluator,
        answer,
        **kwargs,
    ):
        before_retrieval = kwargs["before_retrieval"]
        self.attempts.append(repair_type)
        self.before_retrievals.append(before_retrieval)

        if repair_type == RepairType.HYBRID_RETRIEVAL:
            empty_retrieval = RetrievalResult(
                query=query,
                documents=[],
                scores=[],
                retrieval_method=before_retrieval.retrieval_method,
            )
            return RepairResult(
                repair_id="failed-hybrid",
                failure_id="",
                repair_type=repair_type,
                before_metrics=before_metrics,
                after_metrics=before_metrics,
                improvement=-1.0,
                status="rejected",
                before_retrieval=before_retrieval,
                after_retrieval=empty_retrieval,
            )

        return self.engine.execute(
            repair_type,
            store,
            query,
            before_metrics,
            relevant_ids,
            evaluator,
            answer,
            **kwargs,
        )

    def validate(self, result):
        return self.engine.validate(result)


def build_low_recall_graph(repair_engine):
    store = VectorStore()
    relevant_one = Chunk(
        chunk_id="relevant-1",
        document_id="policy-1",
        text="refund policy refund request",
    )
    relevant_two = Chunk(
        chunk_id="relevant-2",
        document_id="policy-2",
        text="refund policy deadline information",
    )
    noise = Chunk(
        chunk_id="noise",
        document_id="noise",
        text="general support contact information",
    )
    store.add([relevant_one, relevant_two, noise])

    query = "refund policy deadline"
    answer = "refund policy deadline information"
    before_retrieval = RetrievalResult(
        query=query,
        documents=[relevant_one, noise],
        scores=[0.8, 0.7],
        retrieval_method=RetrievalMethod.VECTOR,
    )
    state = RAGGuardState(
        query=query,
        retrieval_result=before_retrieval,
    )

    def diagnose_with_two_repairs(failure):
        diagnosis = diagnose(failure)
        diagnosis.recommended_repairs = [
            RepairType.HYBRID_RETRIEVAL,
            RepairType.RERANK,
        ]
        return diagnosis

    graph = build_langgraph(
        LowRecallDetector(),
        diagnose_with_two_repairs,
        repair_engine,
        store,
        Evaluator(),
        {"relevant-1", "relevant-2"},
        answer,
    )
    return graph, state, before_retrieval


def test_first_repair_fails_then_rerank_succeeds_after_rollback():
    repair_engine = FailHybridThenRerankEngine()
    graph, state, original_retrieval = build_low_recall_graph(repair_engine)

    result = graph.invoke(state)

    assert result["attempted_repairs"] == [
        RepairType.HYBRID_RETRIEVAL,
        RepairType.RERANK,
    ]
    assert repair_engine.attempts == result["attempted_repairs"]
    assert repair_engine.before_retrievals[1] is original_retrieval
    assert result["repair_result"].repair_type == RepairType.RERANK
    assert result["status"] == "promoted"
    assert result["repair_result"].after_metrics.overall_score > (
        result["repair_result"].before_metrics.overall_score
    )
    assert result["completed_nodes"].count("rollback") == 1
    assert "re_evaluate" in result["completed_nodes"]


def test_langgraph_rolls_back_a_worse_repair():
    graph, state = build_duplicate_graph(WorseRepairEngine())
    original_retrieval = state.retrieval_result

    result = graph.invoke(state)

    assert result["status"] == "escalated"
    assert result["repair_result"].repair_type == RepairType.DEDUPLICATE
    assert result["repair_result"].improvement < 0
    assert result["retrieval_result"] is original_retrieval
    assert result["evaluation_result"] is result["repair_result"].before_metrics
    assert "re_evaluate" in result["completed_nodes"]
    assert "rollback" in result["completed_nodes"]


def test_failure_runs_diagnosis_then_escalates_without_repair_budget():
    graph, state = build_duplicate_graph()
    graph = build_langgraph(
        FailureDetector(Thresholds()), diagnose, RepairEngine(),
        VectorStore(), Evaluator(), {"relevant"}, "Refunds are available.",
        max_repair_attempts=0,
    )

    result = graph.invoke(state)

    assert result["failure_event"] is not None
    assert result["diagnosis"] is not None
    assert result["status"] == "escalated"
    assert "diagnose" in result["completed_nodes"]
    assert result["repair_result"] is None


def test_repeated_repair_is_blocked_and_escalated():
    graph, state = build_duplicate_graph()
    state.attempted_repairs = [RepairType.DEDUPLICATE]

    result = graph.invoke(state)

    assert result["status"] == "escalated"
    assert result["repair_result"] is None
    assert result["attempted_repairs"] == [RepairType.DEDUPLICATE]


def test_maximum_attempts_escalates_after_rollback():
    graph, state = build_duplicate_graph()

    def recommend_two_repairs(failure):
        diagnosis = diagnose(failure)
        diagnosis.recommended_repairs = [
            RepairType.DEDUPLICATE,
            RepairType.RERANK,
        ]
        return diagnosis

    graph = build_langgraph(
        FailureDetector(Thresholds()), recommend_two_repairs,
        WorseRepairEngine(), VectorStore(), Evaluator(), {"relevant"},
        "Refunds are available within 30 days.", max_repair_attempts=1,
    )
    original_retrieval = state.retrieval_result

    result = graph.invoke(state)

    assert result["status"] == "escalated"
    assert len(result["attempted_repairs"]) == 1
    assert result["retrieval_result"] is original_retrieval
    assert "rollback" in result["completed_nodes"]
    assert "escalate" in result["completed_nodes"]


def test_all_failed_permitted_repairs_escalate_after_rollback():
    _, state = build_duplicate_graph()

    def recommend_two_repairs(failure):
        diagnosis = diagnose(failure)
        diagnosis.recommended_repairs = [
            RepairType.DEDUPLICATE,
            RepairType.RERANK,
        ]
        return diagnosis

    graph = build_langgraph(
        FailureDetector(Thresholds()), recommend_two_repairs,
        WorseRepairEngine(), VectorStore(), Evaluator(), {"relevant"},
        "Refunds are available within 30 days.", max_repair_attempts=3,
    )
    result = graph.invoke(state)

    assert result["status"] == "escalated"
    assert result["attempted_repairs"] == [
        RepairType.DEDUPLICATE,
        RepairType.RERANK,
    ]
    assert result["completed_nodes"].count("repair") == 2
    assert result["completed_nodes"].count("rollback") == 2
    assert "escalate" in result["completed_nodes"]


def test_stage_2_three_failed_repairs_rollback_then_escalate():
    _, state = build_duplicate_graph()

    class AlwaysFailRepairEngine:
        def __init__(self):
            self.attempts = []
            self.before_retrievals = []

        def execute(
            self,
            repair_type,
            store,
            query,
            before_metrics,
            relevant_ids,
            evaluator,
            answer,
            **kwargs,
        ):
            before_retrieval = kwargs["before_retrieval"]
            self.attempts.append(repair_type)
            self.before_retrievals.append(before_retrieval)
            failed_retrieval = before_retrieval.model_copy(
                update={"documents": [], "scores": []}
            )

            return RepairResult(
                repair_id=f"failed-{len(self.attempts)}",
                failure_id="",
                repair_type=repair_type,
                before_metrics=before_metrics,
                after_metrics=before_metrics,
                improvement=-1.0,
                status="rejected",
                before_retrieval=before_retrieval,
                after_retrieval=failed_retrieval,
            )

        def validate(self, result):
            return ValidationResult(
                valid=True,
                improved=False,
                score_delta=-1.0,
                message="Repair failed validation.",
            )

    repair_engine = AlwaysFailRepairEngine()

    def recommend_three_repairs(failure):
        diagnosis = diagnose(failure)
        diagnosis.recommended_repairs = [
            RepairType.DEDUPLICATE,
            RepairType.RERANK,
            RepairType.HYBRID_RETRIEVAL,
        ]
        return diagnosis

    graph = build_langgraph(
        FailureDetector(Thresholds()),
        recommend_three_repairs,
        repair_engine,
        VectorStore(),
        Evaluator(),
        {"relevant"},
        "Refunds are available within 30 days.",
        max_repair_attempts=3,
    )
    original_retrieval = state.retrieval_result

    result = graph.invoke(state)

    assert result["status"] == "escalated"
    assert result["attempted_repairs"] == [
        RepairType.DEDUPLICATE,
        RepairType.RERANK,
        RepairType.HYBRID_RETRIEVAL,
    ]
    assert len(repair_engine.attempts) == 3
    assert repair_engine.before_retrievals[0] is original_retrieval
    assert repair_engine.before_retrievals[1] is original_retrieval
    assert repair_engine.before_retrievals[2] is original_retrieval
    assert result["retrieval_result"] is original_retrieval
    assert result["completed_nodes"].count("repair") == 3
    assert result["completed_nodes"].count("re_evaluate") == 3
    assert result["completed_nodes"].count("validate") == 3
    assert result["completed_nodes"].count("rollback") == 3
    assert result["completed_nodes"].count("escalate") == 1


def test_repair_budget_loads_from_environment(monkeypatch):
    monkeypatch.setenv("RAGGUARD_MAX_REPAIR_ATTEMPTS", "2")

    assert load_settings("configs/development.yaml").max_repair_attempts == 2


def test_unsupported_policy_repair_escalates_without_execution():
    graph, state = build_duplicate_graph()

    def recommends_unimplemented_repair(failure):
        diagnosis = diagnose(failure)
        diagnosis.recommended_repairs = [RepairType.HUMAN_ESCALATION]
        return diagnosis

    graph = build_langgraph(
        FailureDetector(Thresholds()), recommends_unimplemented_repair,
        RepairEngine(), VectorStore(), Evaluator(), {"relevant"},
        "Refunds are available within 30 days.",
    )
    result = graph.invoke(state)

    assert result["status"] == "escalated"
    assert result["repair_result"] is None
