import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ragguard.common.schemas import Document
from ragguard.config import load_settings
from ragguard.storage.vector_store import VectorStore
from ragguard.ingestion.chunker import sentence_aware
from ragguard.evaluation.evaluator import Evaluator
from ragguard.detection.failure_detector import FailureDetector
from ragguard.diagnosis.diagnostic_agent import diagnose
from ragguard.repair.repair_engine import RepairEngine
from ragguard.agents.state import RAGGuardState
from ragguard.agents.graph import run_sequential

def main():
    settings = load_settings()

    docs = [
        Document(
            document_id="refund",
            text="Refunds are available within 30 days of purchase. "
                 "Approved refunds are returned to the original payment method."
        ),
        Document(
            document_id="security",
            text="Security incidents must be reported within 24 hours. "
                 "Incident reports should include the affected system and timestamp."
        ),
        Document(
            document_id="support",
            text="Priority support is available to enterprise customers. "
                 "Standard support responds within two business days."
        ),
    ]

    store = VectorStore()
    chunks = [c for d in docs for c in sentence_aware(d, max_chars=180)]
    store.add(chunks)

    query = "How long do I have to request a refund?"
    answer = "Refunds are available within 30 days of purchase."
    relevant = {c.chunk_id for c in chunks if "30 days" in c.text}

    retrieval = store.search(query, top_k=settings.top_k)
    evaluator = Evaluator()
    baseline = evaluator.evaluate(query, answer, retrieval, relevant)

    state = RAGGuardState(
        query=query,
        retrieval_result=retrieval,
        evaluation_result=baseline,
    )

    detector = FailureDetector(settings.thresholds)
    engine = RepairEngine()

    state = run_sequential(
        state, detector, diagnose, engine, store,
        evaluator, relevant, answer
    )

    print("RAGGuard demo")
    print("=============")
    print(f"Query: {query}")
    print(f"Baseline overall score: {baseline.overall_score:.3f}")
    print(f"Status: {state.status}")

    if state.failure_event:
        print(f"Failure: {state.failure_event.failure_type.value}")
        print(f"Diagnosis: {state.diagnosis.root_cause.value}")

    if state.repair_result:
        print(f"Repair: {state.repair_result.repair_type.value}")
        print(f"After score: {state.repair_result.after_metrics.overall_score:.3f}")
        print(f"Improvement: {state.repair_result.improvement:+.3f}")

    print(f"Attempted repairs: {[x.value for x in state.attempted_repairs]}")

if __name__ == "__main__":
    main()
