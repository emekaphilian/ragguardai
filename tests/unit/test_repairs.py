import pytest

from ragguard.auth.tenant_context import TenantContext
from ragguard.common.enums import RepairType, RetrievalMethod
from ragguard.common.schemas import Chunk, EvaluationResult, RepairResult, RetrievalResult
from ragguard.repair.repair_policy import choose_repair
from ragguard.repair.repair_engine import RepairEngine
from ragguard.repair.deduplicate import deduplicate, retrieval_stats
from ragguard.storage.vector_store import VectorStore
from ragguard.tenants.application_registration import ApplicationRegistration

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


def test_rejected_repair_leaves_source_index_unchanged():
    store = VectorStore()
    context = TenantContext(
        "tenant", "application", "staging", None, (), "tenant-app", "v1", "v1"
    )
    application = ApplicationRegistration(
        ragguard_tenant_id=context.tenant_id,
        application_id=context.application_id,
        display_name="Test application",
        environment=context.environment,
        knowledge_source="managed_index",
        repair_authorized=True,
        context_verification_authorized=True,
        vector_namespace=context.vector_namespace,
    )
    scope = context.scope
    chunks = [
        Chunk(chunk_id="dup-a", document_id="a", text="Refund request general information.", metadata={
            "ragguard_tenant_id": scope.tenant_id,
            "application_id": scope.application_id,
            "environment": scope.environment,
        }),
        Chunk(chunk_id="dup-b", document_id="b", text="Refund request general information.", metadata={
            "ragguard_tenant_id": scope.tenant_id,
            "application_id": scope.application_id,
            "environment": scope.environment,
        }),
        Chunk(chunk_id="policy", document_id="policy", text="Refunds are available within 30 days.", metadata={
            "ragguard_tenant_id": scope.tenant_id,
            "application_id": scope.application_id,
            "environment": scope.environment,
        }),
    ]
    store.add(chunks, namespace="tenant-app")
    original = [(item.chunk_id, item.text, dict(item.metadata)) for item in store.chunks]
    query = "refund request deadline"
    answer = "Refunds are available within 30 days."
    before_retrieval = store.search(query, top_k=2, scope=scope)
    before_metrics = EvaluationResult(
        context_precision=0.5, context_recall=0.5, faithfulness=0.5,
        answer_relevancy=0.5, overall_score=0.5,
    )

    class RejectingEvaluator:
        def evaluate(self, *args, **kwargs):
            return before_metrics

    evaluator = RejectingEvaluator()
    result = RepairEngine().execute(
        RepairType.DEDUPLICATE, store, query, before_metrics, {"policy"}, evaluator,
        answer, context=context, application_registration=application,
        before_retrieval=before_retrieval, top_k=2,
    )
    assert result.improvement == 0
    assert RepairEngine().validate(result).improved is False
    assert [(item.chunk_id, item.text, dict(item.metadata)) for item in store.chunks] == original


def test_repair_engine_rejects_missing_and_cross_application_scope():
    store = VectorStore()
    app_a = TenantContext("tenant", "app-a", "staging", None, (), "shared", "v1", "v1")
    app_b = TenantContext("tenant", "app-b", "staging", None, (), "shared", "v1", "v1")
    registration_a = ApplicationRegistration(
        ragguard_tenant_id=app_a.tenant_id,
        application_id=app_a.application_id,
        display_name="Application A",
        environment=app_a.environment,
        knowledge_source="managed_index",
        repair_authorized=True,
        context_verification_authorized=True,
        vector_namespace=app_a.vector_namespace,
    )
    unauthorized_registration = ApplicationRegistration(
        ragguard_tenant_id=app_a.tenant_id,
        application_id=app_a.application_id,
        display_name="Application A",
        environment=app_a.environment,
        knowledge_source="managed_index",
        vector_namespace=app_a.vector_namespace,
    )
    reader_context = TenantContext(
        "tenant",
        "app-a",
        "staging",
        "reader",
        (),
        "shared",
        "v1",
        "v1",
        application_memberships=(("app-a", "staging", ("reader",)),),
    )
    for context, chunk_id in ((app_a, "a"), (app_b, "b")):
        store.add([Chunk(chunk_id=chunk_id, document_id=chunk_id, text="refund policy", metadata={
            "ragguard_tenant_id": context.tenant_id,
            "application_id": context.application_id,
            "environment": context.environment,
        })], namespace=context.vector_namespace)
    before_metrics = EvaluationResult(
        context_precision=0.5, context_recall=0.5, faithfulness=0.5,
        answer_relevancy=0.5, overall_score=0.5,
    )
    before_b = store.search("refund policy", scope=app_b.scope)

    execute = getattr(RepairEngine(), "execute")
    with pytest.raises(TypeError):
        execute(
            RepairType.DEDUPLICATE, store, "refund policy", before_metrics, {"a"},
            EvaluatorStub(), "refund policy", context=app_a,
        )
    with pytest.raises(TypeError):
        execute(
            RepairType.DEDUPLICATE, store, "refund policy", before_metrics, {"a"},
            EvaluatorStub(), "refund policy", context=app_a,
            application_registration=registration_a, namespace="shared",
        )
    with pytest.raises(PermissionError, match="authorized"):
        execute(
            RepairType.DEDUPLICATE, store, "refund policy", before_metrics, {"a"},
            EvaluatorStub(), "refund policy", context=app_a,
            application_registration=unauthorized_registration,
        )
    with pytest.raises(PermissionError, match="operator authorization"):
        execute(
            RepairType.DEDUPLICATE, store, "refund policy", before_metrics, {"a"},
            EvaluatorStub(), "refund policy", context=reader_context,
            application_registration=registration_a,
        )
    with pytest.raises(ValueError, match="outside the application scope"):
        execute(
            RepairType.DEDUPLICATE, store, "refund policy", before_metrics, {"a"},
            EvaluatorStub(), "refund policy", context=app_a,
            application_registration=registration_a, before_retrieval=before_b,
        )


def test_privileged_repair_requires_authorization_and_isolates_shared_namespace():
    store = VectorStore()
    app_a = TenantContext("tenant", "app-a", "staging", None, (), "shared", "v1", "v1")
    app_b = TenantContext("tenant", "app-b", "staging", None, (), "shared", "v1", "v1")
    registration_a = ApplicationRegistration(
        ragguard_tenant_id=app_a.tenant_id,
        application_id=app_a.application_id,
        display_name="Application A",
        environment=app_a.environment,
        knowledge_source="managed_index",
        repair_authorized=True,
        context_verification_authorized=True,
        vector_namespace=app_a.vector_namespace,
    )
    reader_context = TenantContext(
        "tenant",
        "app-a",
        "staging",
        "reader",
        (),
        "shared",
        "v1",
        "v1",
        application_memberships=(("app-a", "staging", ("reader",)),),
    )
    for context in (app_a, app_b):
        store.add(
            [
                Chunk(
                    chunk_id=context.application_id,
                    document_id=context.application_id,
                    text="refund policy",
                    metadata={
                        "ragguard_tenant_id": context.tenant_id,
                        "application_id": context.application_id,
                        "environment": context.environment,
                    },
                )
            ],
            namespace=context.vector_namespace,
        )
    metrics = EvaluationResult(
        context_precision=0.5,
        context_recall=0.5,
        faithfulness=0.5,
        answer_relevancy=0.5,
        overall_score=0.5,
    )
    execute_privileged = RepairEngine().execute_privileged
    arguments = (
        RepairType.DEDUPLICATE,
        store,
        "refund policy",
        metrics,
        {"app-a"},
        EvaluatorStub(),
        "refund policy",
    )

    with pytest.raises(TypeError):
        execute_privileged(*arguments, namespace="shared")
    with pytest.raises(PermissionError, match="operator authorization"):
        execute_privileged(
            *arguments,
            namespace="shared",
            context=reader_context,
            application_registration=registration_a,
        )
    with pytest.raises(PermissionError, match="must match"):
        execute_privileged(
            *arguments,
            namespace="other",
            context=app_a,
            application_registration=registration_a,
        )

    result = execute_privileged(
        *arguments,
        namespace="shared",
        context=app_a,
        application_registration=registration_a,
    )
    assert {
        chunk.metadata["application_id"]
        for chunk in result.after_retrieval.documents
    } == {"app-a"}


class EvaluatorStub:
    def evaluate(self, *args, **kwargs):
        return EvaluationResult(
            context_precision=0.5, context_recall=0.5, faithfulness=0.5,
            answer_relevancy=0.5, overall_score=0.5,
        )
