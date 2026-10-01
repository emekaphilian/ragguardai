"""Small, local application service used by the HTTP API.

It deliberately keeps state in process for the offline edition.  The API is
backed by real documents and retrieval results; a production adapter can
replace this class with durable stores without changing route contracts.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from ragguard.common.schemas import Document
from ragguard.auth.tenant_context import TenantContext
from ragguard.ingestion.document_processor import process_document
from ragguard.ingestion.loaders import load_directory
from ragguard.evaluation.metrics import answer_relevancy, faithfulness
from ragguard.retrieval.retriever import retrieve
from ragguard.retrieval.hybrid import _tokens
from ragguard.storage.vector_store import VectorStore
from ragguard.persistence.observation_repository import create_observation_repository


observation_repository = create_observation_repository()


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
        self._rebuild_index()
        return len(documents)

    def _rebuild_index(self) -> None:
        chunks = [chunk for doc in self.documents.values() for chunk in process_document(doc)]
        self.store = VectorStore()
        if chunks:
            self.store.add(chunks)

    def delete_document(self, document_id: str, context: TenantContext | None = None) -> bool:
        document = self.documents.get(document_id)
        if document is None:
            return False
        if context is not None and document.metadata.get("tenant_namespace") != context.vector_namespace:
            return False
        del self.documents[document_id]
        self._rebuild_index()
        return True

    def add_document(self, name: str, text: str, context: TenantContext | None = None, ingestion_method: str = "integration") -> dict:
        clean_name = "".join(c if c.isalnum() or c in "-_" else "-" for c in name).strip("-") or "document"
        document = Document(document_id=f"{clean_name}-{uuid4().hex[:8]}", text=text, metadata={"source": name, "ingestion_method": ingestion_method})
        self.ingest_documents([document], context=context)
        return self.document_rows(context)[-1]

    @staticmethod
    def _answer(query: str, chunks: list) -> str:
        if not chunks:
            return "I could not find any indexed source material for that question. Add documents and try again."
        # Rank source sentences by the query terms and quote only retrieved text.
        query_tokens = _tokens(query)
        sentences: list[tuple[int, int, str]] = []
        order = 0
        for chunk in chunks:
            for line in chunk.text.splitlines():
                if line.strip().startswith("#") or re.match(r"^\s*\d+\.\s+.+Policy\s*$", line):
                    continue
                for sentence in re.split(r"(?<=[.!?])\s+", line.strip()):
                    sentence = sentence.strip()
                    if sentence:
                        overlap = len(query_tokens & _tokens(sentence))
                        if overlap:
                            sentences.append((overlap, order, sentence))
                        order += 1
        sentences.sort(key=lambda item: (-item[0], item[1]))
        chosen = list(dict.fromkeys(sentence for _, _, sentence in sentences[:3]))
        return " ".join(chosen) or "I could not find a sufficiently relevant passage in the indexed documents to answer that question."

    def query(self, query: str, top_k: int = 5, method: str = "hybrid", context: TenantContext | None = None) -> dict:
        started = perf_counter()
        retrieval = retrieve(self.store, query, method=method, top_k=top_k, context=context)
        answer = self._answer(query, retrieval.documents)
        latency_ms = round((perf_counter() - started) * 1000, 2)
        # This is a lexical query-term match proxy, not a labeled quality score.
        score = sum(retrieval.scores) / len(retrieval.scores) if retrieval.scores else 0.0
        status = "grounded" if retrieval.documents and max(retrieval.scores, default=0.0) >= 0.15 else "no_match"
        source_coverage = 1.0 if status == "grounded" else 0.0
        quality = {
            "term_match": round(min(1.0, score), 3),
            "source_coverage": source_coverage,
            "answer_relevancy": round(answer_relevancy(query, answer), 3),
            "faithfulness": round(faithfulness(answer, retrieval), 3),
        }
        if status == "no_match":
            answer = "I could not find a sufficiently relevant passage in the indexed documents to answer that question."
            quality["answer_relevancy"] = round(answer_relevancy(query, answer), 3)
            quality["faithfulness"] = round(faithfulness(answer, retrieval), 3)
        quality["overall_quality"] = round(sum(quality.values()) / len(quality), 3)
        run = {
            "id": f"run-{uuid4().hex[:8]}", "query": query, "status": status,
            "method": retrieval.retrieval_method.value, "latency_ms": latency_ms,
            "created_at": datetime.now(timezone.utc).isoformat(), "quality": quality,
            "tenant_id": context.tenant_id if context else "development",
        }
        self.runs.insert(0, run)
        if status == "no_match":
            failure = {"id": f"failure-{uuid4().hex[:8]}", "type": "NO_RETRIEVAL_MATCH", "severity": "high", "query": query, "status": "open", "evidence": ["No indexed chunk matched the query."], "created_at": run["created_at"], "tenant_id": run["tenant_id"]}
            self.failures.insert(0, failure)
        sources = retrieval.documents if status == "grounded" else []
        scores = retrieval.scores if status == "grounded" else []
        return {"answer": answer, "rag_status": status, "retrieval_quality": quality, "retrieval_method": retrieval.retrieval_method.value, "latency_ms": run["latency_ms"], "sources": [{"chunk_id": c.chunk_id, "document_id": c.document_id, "source": c.metadata.get("source", c.document_id), "section": c.metadata.get("section_title"), "text": c.text, "score": round(s, 4)} for c, s in zip(sources, scores)], "run": run}

    def document_rows(self, context: TenantContext | None = None) -> list[dict]:
        chunks_by_document: dict[str, list] = {}
        for chunk in self.store.chunks:
            chunks_by_document.setdefault(chunk.document_id, []).append(chunk)
        namespace = context.vector_namespace if context else None
        dimensions = len(self.store.vectorizer.vocabulary_) if self.store.matrix is not None else 0
        rows = []
        for document in self.documents.values():
            if namespace is not None and document.metadata.get("tenant_namespace") != namespace:
                continue
            chunks = chunks_by_document.get(document.document_id, [])
            rows.append({
                "id": document.document_id,
                "source": document.metadata.get("source", document.document_id),
                "ingestion_method": document.metadata.get("ingestion_method", "directory"),
                "status": "indexed" if chunks else "no_chunks",
                "chunks": len(chunks),
                "characters": len(document.text),
                "embedding_model": "local-tfidf",
                "embedding_dimensions": dimensions,
                "embedding_vectors": len(chunks),
            })
        return rows

    def dashboard(self, context: TenantContext | None = None) -> dict:
        tenant_id = context.tenant_id if context else None
        runs = [run for run in self.runs if tenant_id is None or run["tenant_id"] == tenant_id]
        failures_list = [failure for failure in self.failures if tenant_id is None or failure["tenant_id"] == tenant_id]
        run_count = len(runs)
        failures = len(failures_list)
        latest_quality = runs[0]["quality"] if runs else {}
        metric_defaults = {
            "term_match": None,
            "source_coverage": None,
            "answer_relevancy": None,
            "faithfulness": None,
            "overall_quality": None,
        }
        chunks = [chunk for chunk in self.store.chunks if context is None or chunk.metadata.get("tenant_namespace") == context.vector_namespace]
        return {"metrics": {**metric_defaults, **latest_quality, "failure_rate": round(failures / run_count, 3) if run_count else None, "repair_success_rate": None, "total_runs": run_count, "total_failures": failures}, "embedding": {"model": "local-tfidf", "dimension": len(self.store.vectorizer.vocabulary_) if self.store.matrix is not None else 0, "vectors": len(chunks), "latency_ms": runs[0]["latency_ms"] if runs else None}, "index": {"documents": len(self.document_rows(context)), "chunks": len(chunks), "last_refresh": self.started_at.isoformat()}, "recent_failures": failures_list[:10]}


workspace = Workspace()
