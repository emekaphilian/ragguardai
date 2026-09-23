from uuid import uuid4
from types import SimpleNamespace

from ragguard.common.enums import RepairType
from ragguard.common.schemas import RepairResult, ValidationResult

from .deduplicate import deduplicate, retrieval_stats
from .hybrid_retrieval import run_hybrid
from .reranking import rerank


class RepairEngine:
    def execute(
        self, repair_type, store, query, before_metrics, relevant_ids, evaluator,
        answer, before_retrieval=None, top_k=5, namespace=None,
    ):
        """Execute one retrieval repair without mutating the source index.

        The caller owns promotion or rollback by choosing which returned retrieval
        state becomes active.  This keeps a rejected experiment reversible.
        """
        before_retrieval = before_retrieval or store.search(
            query, top_k=top_k, namespace=namespace
        )
        if repair_type == RepairType.HYBRID_RETRIEVAL:
            # The hybrid adapter consumes ``chunks`` directly, so scope that
            # view explicitly instead of allowing a repair to cross tenants.
            hybrid_store = store
            if namespace is not None:
                hybrid_store = SimpleNamespace(
                    chunks=[
                        chunk for chunk in store.chunks
                        if chunk.metadata.get("tenant_namespace") == namespace
                    ],
                    search=lambda q, k: store.search(q, k, namespace=namespace),
                )
            retrieval = run_hybrid(hybrid_store, query, top_k=top_k)
        elif repair_type == RepairType.RERANK:
            retrieval = rerank(
                query, store.search(query, top_k=top_k, namespace=namespace)
            )
        elif repair_type == RepairType.DEDUPLICATE:
            candidates = store.search(
                query, top_k=max(top_k, len(store.chunks)), namespace=namespace
            )
            retrieval = deduplicate(candidates, top_k=top_k)
        else:
            retrieval = store.search(query, top_k=top_k, namespace=namespace)

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
