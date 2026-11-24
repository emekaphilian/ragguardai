from uuid import uuid4
from types import SimpleNamespace

from ragguard.auth.application_access import require_application_repair_authorization
from ragguard.auth.tenant_context import TenantContext
from ragguard.common.enums import RepairType
from ragguard.common.schemas import RepairResult
from ragguard.tenants.application_registration import ApplicationRegistration
from ragguard.validation.validator import validate_repair

from .deduplicate import deduplicate, retrieval_stats
from .hybrid_retrieval import run_hybrid
from .reranking import rerank
from .repair_policy import EXECUTABLE_REPAIRS


class UnsupportedRepairError(ValueError):
    """Raised when policy requests a repair without an implemented strategy."""


class RepairEngine:
    def execute(
        self, repair_type, store, query, before_metrics, relevant_ids, evaluator,
        answer, *, context: TenantContext,
        application_registration: ApplicationRegistration,
        before_retrieval=None, top_k=5,
    ):
        """Execute one retrieval repair without mutating the source index.

        The caller owns promotion or rollback by choosing which returned retrieval
        state becomes active.  This keeps a rejected experiment reversible.
        """
        require_application_repair_authorization(context, application_registration)
        scope = context.scope
        expected_scope = (
            scope.vector_namespace,
            scope.tenant_id,
            scope.application_id,
            scope.environment,
        )
        chunks = [
            chunk for chunk in store.chunks
            if (
                chunk.metadata.get("tenant_namespace"),
                chunk.metadata.get("ragguard_tenant_id"),
                chunk.metadata.get("application_id"),
                chunk.metadata.get("environment"),
            ) == expected_scope
        ]
        search = lambda q, k: store.search(q, k, scope=scope)
        return self._execute(
            repair_type,
            query,
            before_metrics,
            relevant_ids,
            evaluator,
            answer,
            before_retrieval=before_retrieval,
            top_k=top_k,
            chunks=chunks,
            search=search,
            scope=scope,
        )

    def execute_privileged(
        self, repair_type, store, query, before_metrics, relevant_ids, evaluator,
        answer, *, namespace: str, context: TenantContext,
        application_registration: ApplicationRegistration,
        before_retrieval=None, top_k=5,
    ):
        """Run an administrative repair within an authorized application scope."""
        require_application_repair_authorization(context, application_registration)
        if not isinstance(namespace, str) or not namespace.strip():
            raise ValueError("Privileged repair requires an explicit namespace.")
        scope = context.scope
        if namespace != scope.vector_namespace:
            raise PermissionError(
                "Privileged repair namespace must match the authorized application."
            )
        expected_scope = (
            scope.vector_namespace,
            scope.tenant_id,
            scope.application_id,
            scope.environment,
        )
        chunks = [
            chunk for chunk in store.chunks
            if (
                chunk.metadata.get("tenant_namespace"),
                chunk.metadata.get("ragguard_tenant_id"),
                chunk.metadata.get("application_id"),
                chunk.metadata.get("environment"),
            ) == expected_scope
        ]
        search = lambda q, k: store.search(q, k, scope=scope)
        return self._execute(
            repair_type,
            query,
            before_metrics,
            relevant_ids,
            evaluator,
            answer,
            before_retrieval=before_retrieval,
            top_k=top_k,
            chunks=chunks,
            search=search,
            scope=scope,
        )

    def _execute(
        self, repair_type, query, before_metrics, relevant_ids, evaluator,
        answer, *, before_retrieval, top_k, chunks, search, scope=None,
        namespace=None,
    ):
        if repair_type not in EXECUTABLE_REPAIRS:
            raise UnsupportedRepairError(
                f"Repair strategy {repair_type} has no executable implementation."
            )

        if before_retrieval is None:
            before_retrieval = search(query, top_k)
        if scope is not None:
            for chunk in before_retrieval.documents:
                actual_scope = (
                    chunk.metadata.get("tenant_namespace"),
                    chunk.metadata.get("ragguard_tenant_id"),
                    chunk.metadata.get("application_id"),
                    chunk.metadata.get("environment"),
                )
                if actual_scope != (
                    scope.vector_namespace,
                    scope.tenant_id,
                    scope.application_id,
                    scope.environment,
                ):
                    raise ValueError("Pre-retrieved repair context is outside the application scope.")
        if namespace is not None:
            if any(
                chunk.metadata.get("tenant_namespace") != namespace
                for chunk in before_retrieval.documents
            ):
                raise ValueError("Pre-retrieved repair context is outside the privileged namespace.")
        if repair_type == RepairType.HYBRID_RETRIEVAL:
            hybrid_store = SimpleNamespace(chunks=chunks, search=search)
            retrieval = run_hybrid(hybrid_store, query, top_k=top_k)
        elif repair_type == RepairType.RERANK:
            retrieval = rerank(query, search(query, top_k))
        elif repair_type == RepairType.DEDUPLICATE:
            candidates = search(query, max(top_k, len(chunks)))
            retrieval = deduplicate(candidates, top_k=top_k)
        else:
            retrieval = search(query, top_k)

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
            before_retrieval=before_retrieval,
            after_retrieval=retrieval,
            before_retrieval_stats=retrieval_stats(before_retrieval),
            after_retrieval_stats=retrieval_stats(retrieval),
        )

    def validate(self, result):
        return validate_repair(result)
