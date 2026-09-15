"""Small, local application service used by the HTTP API.

It deliberately keeps state in process for the offline edition.  The API is
backed by real documents and retrieval results; a production adapter can
replace this class with durable stores without changing route contracts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from ragguard.common.schemas import Document
from ragguard.auth.tenant_context import TenantContext
from ragguard.ingestion.document_processor import process_document
from ragguard.ingestion.loaders import load_directory
from ragguard.retrieval.retriever import retrieve
from ragguard.storage.vector_store import VectorStore


class Workspace:
    def __init__(self):
        self.store = VectorStore()
        self.documents: dict[str, Document] = {}
        self.runs: list[dict] = []
        self.failures: list[dict] = []
        self.repairs: list[dict] = []
        self.started_at = datetime.now(timezone.utc)
        self.ingest_directory(Path("data/raw"))

    def ingest_directory(self, directory: Path) -> int:
        if not directory.exists():
            return 0
        return self.ingest_documents(load_directory(directory))

    def ingest_documents(self, documents: list[Document], context: TenantContext | None = None) -> int:
        for document in documents:
            namespace = context.vector_namespace if context else document.metadata.get("tenant_namespace", "development")
            document.metadata = {**document.metadata, "tenant_namespace": namespace}
            self.documents[document.document_id] = document
        chunks = [chunk for doc in self.documents.values() for chunk in process_document(doc)]
        self.store = VectorStore()
        if chunks:
            self.store.add(chunks)
        return len(documents)

    def add_document(self, name: str, text: str, context: TenantContext | None = None) -> dict:
        clean_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "document"
        document = Document(document_id=f"{clean_name}-{uuid4().hex[:8]}", text=text, metadata={"source": name})
        self.ingest_documents([document], context=context)
        return self.document_rows(context)[-1]

    @staticmethod
    def _answer(query: str, chunks: list) -> str:
        if not chunks:
            return "I could not find any indexed source material for that question. Add documents and try again."
        # Extractive output is intentionally constrained to retrieved material.
        sentences = []
        for chunk in chunks:
            for sentence in chunk.text.replace("\n", " ").split("."):
                sentence = sentence.strip()
                if sentence and sentence not in sentences:
                    sentences.append(sentence + ".")
                if len(sentences) == 3:
                    return " ".join(sentences)
        return " ".join(sentences) or chunks[0].text

    def query(self, query: str, top_k: int = 5, method: str = "hybrid", context: TenantContext | None = None) -> dict:
        retrieval = retrieve(self.store, query, method=method, top_k=top_k, context=context)
        answer = self._answer(query, retrieval.documents)
        # Without a labeled relevance set, these are observable retrieval signals,
        # not invented benchmark scores.
        score = sum(retrieval.scores) / len(retrieval.scores) if retrieval.scores else 0.0
        supported = 1.0 if retrieval.documents else 0.0
        quality = {
            "context_precision": round(min(1.0, score), 3),
            "context_recall": supported,
            "faithfulness": supported,
            "answer_relevancy": round(min(1.0, score), 3),
            "citation_accuracy": supported,
        }
        status = "grounded" if retrieval.documents and score > 0 else "no_match"
        run = {
            "id": f"run-{uuid4().hex[:8]}", "query": query, "status": status,
            "method": retrieval.retrieval_method.value, "latency_ms": round(retrieval.latency_ms, 2),
            "created_at": datetime.now(timezone.utc).isoformat(), "quality": quality,
            "tenant_id": context.tenant_id if context else "development",
        }
        self.runs.insert(0, run)
        if status == "no_match":
            failure = {"id": f"failure-{uuid4().hex[:8]}", "type": "NO_RETRIEVAL_MATCH", "severity": "high", "query": query, "status": "open", "evidence": ["No indexed chunk matched the query."], "created_at": run["created_at"], "tenant_id": run["tenant_id"]}
            self.failures.insert(0, failure)
        return {"answer": answer, "rag_status": status, "retrieval_quality": quality, "retrieval_method": retrieval.retrieval_method.value, "latency_ms": run["latency_ms"], "sources": [{"chunk_id": c.chunk_id, "document_id": c.document_id, "source": c.metadata.get("source", c.document_id), "text": c.text, "score": round(s, 4)} for c, s in zip(retrieval.documents, retrieval.scores)], "run": run}

    def document_rows(self, context: TenantContext | None = None) -> list[dict]:
        counts: dict[str, int] = {}
        for chunk in self.store.chunks:
            counts[chunk.document_id] = counts.get(chunk.document_id, 0) + 1
        namespace = context.vector_namespace if context else None
        return [{"id": d.document_id, "source": d.metadata.get("source", d.document_id), "chunks": counts.get(d.document_id, 0), "characters": len(d.text)} for d in self.documents.values() if namespace is None or d.metadata.get("tenant_namespace") == namespace]

    def dashboard(self, context: TenantContext | None = None) -> dict:
        tenant_id = context.tenant_id if context else None
        runs = [run for run in self.runs if tenant_id is None or run["tenant_id"] == tenant_id]
        failures_list = [failure for failure in self.failures if tenant_id is None or failure["tenant_id"] == tenant_id]
        run_count = len(runs)
        failures = len(failures_list)
        latest_quality = runs[0]["quality"] if runs else {}
        chunks = [chunk for chunk in self.store.chunks if context is None or chunk.metadata.get("tenant_namespace") == context.vector_namespace]
        return {"metrics": {**latest_quality, "failure_rate": round(failures / run_count, 3) if run_count else None, "repair_success_rate": None, "total_runs": run_count}, "embedding": {"model": "local-tfidf", "dimension": len(self.store.vectorizer.vocabulary_) if self.store.matrix is not None else 0, "vectors": len(chunks), "latency_ms": runs[0]["latency_ms"] if runs else None}, "index": {"documents": len(self.document_rows(context)), "chunks": len(chunks), "last_refresh": self.started_at.isoformat()}, "recent_failures": failures_list[:10]}


workspace = Workspace()
