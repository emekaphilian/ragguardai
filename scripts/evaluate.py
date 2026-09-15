import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from ragguard.config import load_settings
from ragguard.storage.vector_store import VectorStore
from ragguard.common.schemas import Document
from ragguard.ingestion.chunker import sentence_aware
from ragguard.evaluation.evaluator import Evaluator

def main():
    settings = load_settings()
    docs = [
        Document(document_id="refund", text="Refunds are available within 30 days of purchase."),
        Document(document_id="security", text="Security incidents must be reported within 24 hours."),
        Document(document_id="support", text="Standard support responds within two business days."),
    ]
    store = VectorStore()
    chunks = [c for d in docs for c in sentence_aware(d, 120)]
    store.add(chunks)

    evaluator = Evaluator()
    rows = [
        (
            "refund deadline",
            "Refunds are available within 30 days of purchase.",
            {c.chunk_id for c in chunks if "30 days" in c.text},
        ),
        (
            "security incident deadline",
            "Security incidents must be reported within 24 hours.",
            {c.chunk_id for c in chunks if "24 hours" in c.text},
        ),
    ]

    for query, answer, relevant in rows:
        retrieval = store.search(query, settings.top_k)
        metrics = evaluator.evaluate(query, answer, retrieval, relevant)
        print(
            f"{query}: overall={metrics.overall_score:.3f}, "
            f"precision={metrics.context_precision:.3f}, "
            f"recall={metrics.context_recall:.3f}"
        )

if __name__ == "__main__":
    main()
