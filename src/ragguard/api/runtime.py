"""Workspace service backed by memory locally and PostgreSQL in shared deployments."""
from __future__ import annotations

import re
import json
import os
import hashlib
from functools import wraps
from threading import RLock
from datetime import datetime, timezone
from pathlib import Path
from time import perf_counter
from uuid import uuid4

from ragguard.common.schemas import Document
from ragguard.common.capabilities import capability_execution, capability_state
from ragguard.auth.tenant_context import TenantContext
from ragguard.ingestion.document_processor import process_document
from ragguard.ingestion.loaders import load_directory
from ragguard.evaluation.metrics import answer_relevancy, faithfulness
from ragguard.retrieval.retriever import retrieve
from ragguard.retrieval.hybrid import _tokens
from ragguard.storage.vector_store import VectorStore
from ragguard.persistence.observation_repository import create_observation_repository
from ragguard.persistence.application_repository import create_application_repository
from ragguard.config import load_settings
from ragguard.persistence.workspace_repository import (
    InMemoryWorkspaceRepository,
    PostgreSQLWorkspaceRepository,
    create_workspace_repository,
)
from ragguard.auth.repository import create_auth_repository
from ragguard.detection.live_detector import LiveFailureDetector
from ragguard.evaluation.live import (
    ObservationSource,
    RAGObservation,
    RetrievedChunkObservation,
)
from ragguard.evaluation.live_evaluator import LiveEvaluator


observation_repository = create_observation_repository()
application_repository = create_application_repository()
auth_repository = create_auth_repository()
workspace_repository = create_workspace_repository()


class _ActivityView:
    def __init__(self, repository, kind):
        self.repository, self.kind = repository, kind
    def __iter__(self): return iter(self.repository.list_activity(self.kind))
    def __len__(self): return len(self.repository.list_activity(self.kind))
    def __getitem__(self, index): return self.repository.list_activity(self.kind)[index]
    def __eq__(self, other): return self.repository.list_activity(self.kind) == other
    def insert(self, index, value):
        if index != 0:
            raise ValueError("Workspace activity only supports newest-first insertion.")
        self.repository.append_activity(self.kind, value)
    def clear(self): self.repository.clear_activity(self.kind)


def _workspace_locked(method):
    @wraps(method)
    def guarded(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)
    return guarded


class Workspace:
    def __init__(self, raw_directory: Path = Path("data/raw"), recycle_directory: Path = Path("data/recycle_bin"), repository=None):
        self._lock = RLock()
        self.store = VectorStore()
        self.repository = repository or workspace_repository
        self.documents: dict[tuple[str, str, str, str], Document] = {}
        self.raw_directory = raw_directory
        self.recycle_directory = recycle_directory
        self.recycled_documents: dict[tuple[str, str, str, str], tuple[Document, str | None]] = {}
        self.recycle_paths: dict[tuple[str, str, str, str], Path] = {}
        self.runs = _ActivityView(self.repository, "runs")
        self.failures = _ActivityView(self.repository, "failures")
        self.repairs = _ActivityView(self.repository, "repairs")
        self.started_at = datetime.now(timezone.utc)
        if not isinstance(self.repository, PostgreSQLWorkspaceRepository):
            self._load_recycle_bin()
        if isinstance(self.repository, InMemoryWorkspaceRepository):
            self.ingest_directory(self.raw_directory)

    @staticmethod
    def _identity(document: Document):
        md = document.metadata
        return (str(md.get("ragguard_tenant_id", "development")), str(md.get("application_id", "development")), str(md.get("environment", "development")), document.document_id)

    @staticmethod
    def _identity_for(document_id: str, context: TenantContext | None):
        if context is None:
            return ("development", "development", "development", document_id)
        return (context.tenant_id, context.application_id, context.environment, document_id)

    @_workspace_locked
    def refresh(self):
        if not isinstance(self.repository, PostgreSQLWorkspaceRepository):
            return
        rows = self.repository.list_documents()
        self.documents = {self._identity(document): document for document, _, _ in rows}
        self.recycled_documents = {
            self._identity(document): (document, source_path)
            for document, recycled, source_path in self.repository.list_documents(include_recycled=True)
            if recycled
        }
        self._rebuild_index()

    @staticmethod
    def _safe_document_key(document_id: str, identity=None) -> str:
        readable = "".join(char if char.isalnum() or char in "-_" else "_" for char in document_id)
        identity_value = "\0".join(identity) if identity else document_id
        return f"{readable[:96]}-{hashlib.sha256(identity_value.encode('utf-8')).hexdigest()[:16]}"

    def _recycle_record_path(self, document_id: str, identity=None) -> Path:
        return self.recycle_directory / f"{self._safe_document_key(document_id, identity)}.json"

    def _recycle_source_path(self, document_id: str, identity=None) -> Path:
        return self.recycle_directory / f"{self._safe_document_key(document_id, identity)}.source"

    def _load_recycle_bin(self) -> None:
        if not self.recycle_directory.exists():
            return
        for path in self.recycle_directory.glob("*.json"):
            try:
                record = json.loads(path.read_text(encoding="utf-8"))
                document = Document.model_validate(record["document"])
                identity = self._identity(document)
                self.recycled_documents[identity] = (
                    document,
                    record.get("source_relative_path"),
                )
                self.recycle_paths[identity] = path
            except (OSError, ValueError, KeyError):
                # Leave malformed records in place for manual recovery.
                continue

    def ingest_directory(self, directory: Path) -> int:
        if not directory.exists():
            return 0
        return self.ingest_documents(load_directory(directory))

    @_workspace_locked
    def ingest_documents(self, documents: list[Document], context: TenantContext | None = None) -> int:
        prepared = []
        for document in documents:
            namespace = context.vector_namespace if context else document.metadata.get("tenant_namespace", "development")
            document.metadata = {
                **document.metadata,
                "tenant_namespace": namespace,
                "ragguard_tenant_id": context.tenant_id if context else document.metadata.get("ragguard_tenant_id", "development"),
                "application_id": context.application_id if context else document.metadata.get("application_id", "development"),
                "environment": context.environment if context else document.metadata.get("environment", "development"),
                "identity_scope_explicit": bool(context) or bool(document.metadata.get("identity_scope_explicit")),
            }
            prepared.append(document)
        self.repository.save_documents(prepared)
        for document in prepared:
            self.documents[self._identity(document)] = document
        self._rebuild_index()
        return len(documents)

    def _rebuild_index(self) -> None:
        chunks = [chunk for doc in self.documents.values() for chunk in process_document(doc)]
        store = VectorStore()
        if chunks:
            store.add(chunks)
        self.store = store

    @_workspace_locked
    def delete_document(self, document_id: str, context: TenantContext | None = None) -> bool:
        self.refresh()
        identity = self._identity_for(document_id, context)
        document = self.documents.get(identity)
        if document is None and context is not None:
            identity, document = next(((key, item) for key, item in self.documents.items()
                                       if key[3] == document_id
                                       and not item.metadata.get("identity_scope_explicit")
                                       and item.metadata.get("tenant_namespace") == context.vector_namespace), (identity, None))
        if document is None:
            return False
        if context is not None and document.metadata.get("tenant_namespace") != context.vector_namespace:
            return False
        self.recycle_directory.mkdir(parents=True, exist_ok=True)
        source_relative_path = None
        source = document.metadata.get("source")
        if isinstance(source, str):
            source_path = Path(source).resolve()
            raw_root = self.raw_directory.resolve()
            try:
                source_relative_path = str(source_path.relative_to(raw_root))
            except ValueError:
                pass
            else:
                if source_path.is_file() and not isinstance(self.repository, PostgreSQLWorkspaceRepository):
                    os.replace(source_path, self._recycle_source_path(document_id, identity))
                    source_relative_path = str(source_path.relative_to(raw_root))
        self.repository.save_document(document, recycled=True, source_relative_path=source_relative_path)
        if not isinstance(self.repository, PostgreSQLWorkspaceRepository):
            record_path = self._recycle_record_path(document_id, identity)
            temporary_path = record_path.with_suffix(".json.tmp")
            temporary_path.write_text(json.dumps({"document": document.model_dump(mode="json"), "source_relative_path": source_relative_path}, ensure_ascii=False), encoding="utf-8")
            os.replace(temporary_path, record_path)
            self.recycle_paths[identity] = record_path
        self.recycled_documents[identity] = (document, source_relative_path)
        del self.documents[identity]
        self._rebuild_index()
        return True

    def recycled_document_rows(self, context: TenantContext | None = None) -> list[dict]:
        rows = []
        for identity, (document, _) in self.recycled_documents.items():
            if context is not None and document.metadata.get("identity_scope_explicit") and identity[:3] != (context.tenant_id, context.application_id, context.environment):
                continue
            if context is not None and document.metadata.get("tenant_namespace") != context.vector_namespace:
                continue
            rows.append({
                "id": document.document_id,
                "source": document.metadata.get("source", document.document_id),
                "ingestion_method": document.metadata.get("ingestion_method", "directory"),
                "status": "in_recycle_bin",
                "characters": len(document.text),
            })
        return rows

    @_workspace_locked
    def restore_document(self, document_id: str, context: TenantContext | None = None) -> bool:
        self.refresh()
        identity = self._identity_for(document_id, context)
        recycled = self.recycled_documents.get(identity)
        if recycled is None and context is not None:
            identity, recycled = next(((key, item) for key, item in self.recycled_documents.items()
                                       if key[3] == document_id
                                       and not item[0].metadata.get("identity_scope_explicit")
                                       and item[0].metadata.get("tenant_namespace") == context.vector_namespace), (identity, None))
        if recycled is None:
            return False
        document, source_relative_path = recycled
        if context is not None and document.metadata.get("tenant_namespace") != context.vector_namespace:
            return False
        if source_relative_path is not None and not isinstance(self.repository, PostgreSQLWorkspaceRepository):
            target = (self.raw_directory / source_relative_path).resolve()
            raw_root = self.raw_directory.resolve()
            try:
                target.relative_to(raw_root)
            except ValueError:
                return False
            if target.exists():
                raise FileExistsError(f"A source file already exists at {target}")
            target.parent.mkdir(parents=True, exist_ok=True)
            record_path = self.recycle_paths.get(identity, self._recycle_record_path(document_id, identity))
            source_path = record_path.with_suffix(".source")
            if not source_path.exists():
                source_path = self._recycle_source_path(document_id)
            os.replace(source_path, target)
        self.repository.save_document(document, recycled=False, source_relative_path=None)
        if not isinstance(self.repository, PostgreSQLWorkspaceRepository):
            self.recycle_paths.pop(identity, None)
            self._recycle_record_path(document_id, identity).unlink(missing_ok=True)
            self._recycle_record_path(document_id).unlink(missing_ok=True)
        self.recycled_documents.pop(identity, None)
        self.recycle_paths.pop(identity, None)
        self.documents[identity] = document
        self._rebuild_index()
        return True

    @_workspace_locked
    def permanently_delete_document(self, document_id: str, context: TenantContext | None = None) -> bool:
        self.refresh()
        identity = self._identity_for(document_id, context)
        recycled = self.recycled_documents.get(identity)
        if recycled is None and context is not None:
            identity, recycled = next(((key, item) for key, item in self.recycled_documents.items()
                                       if key[3] == document_id
                                       and not item[0].metadata.get("identity_scope_explicit")
                                       and item[0].metadata.get("tenant_namespace") == context.vector_namespace), (identity, None))
        if recycled is None:
            return False
        document, _ = recycled
        if context is not None and document.metadata.get("tenant_namespace") != context.vector_namespace:
            return False
        self.repository.delete_document(identity)
        if not isinstance(self.repository, PostgreSQLWorkspaceRepository):
            record_path = self.recycle_paths.pop(identity, self._recycle_record_path(document_id, identity))
            record_path.unlink(missing_ok=True)
            record_path.with_suffix(".source").unlink(missing_ok=True)
            self._recycle_record_path(document_id).unlink(missing_ok=True)
            self._recycle_source_path(document_id).unlink(missing_ok=True)
        self.recycled_documents.pop(identity, None)
        return True

    @_workspace_locked
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

    @_workspace_locked
    def query(
        self,
        query: str,
        top_k: int = 5,
        method: str = "hybrid",
        context: TenantContext | None = None,
        record_run: bool = True,
    ) -> dict:
        self.refresh()
        started = perf_counter()
        retrieval_started = perf_counter()
        retrieval = retrieve(self.store, query, method=method, top_k=top_k, context=context)
        retrieval_latency_ms = round((perf_counter() - retrieval_started) * 1000, 2)
        generation_started = perf_counter()
        answer = self._answer(query, retrieval.documents)
        generation_latency_ms = round((perf_counter() - generation_started) * 1000, 2)
        latency_ms = round((perf_counter() - started) * 1000, 2)
        # This is a lexical query-term match proxy, not a labeled quality score.
        score = sum(retrieval.scores) / len(retrieval.scores) if retrieval.scores else 0.0
        status = "grounded" if retrieval.documents and max(retrieval.scores, default=0.0) >= 0.15 else "no_match"
        observation = RAGObservation(
            contract_version="v1",
            source=ObservationSource(
                application_id=context.application_id if context else "ragguard",
                environment=context.environment if context else "development",
            ),
            query=query,
            retrieved_chunks=[
                RetrievedChunkObservation(id=chunk.chunk_id, score=score)
                for chunk, score in zip(retrieval.documents, retrieval.scores)
            ],
            retrieval_method=retrieval.retrieval_method.value,
            retrieval_required=True,
            retrieval_attempted=True,
            embedding_degraded=False,
            retrieval_latency_ms=retrieval_latency_ms,
            stage_timings_ms={
                "retrieval": retrieval_latency_ms,
                "generation": generation_latency_ms,
            },
            generation_status="succeeded",
            answer=answer,
        )
        reliability_evaluation = LiveEvaluator(
            latency_thresholds_ms=load_settings().live_latency_thresholds_ms,
        ).evaluate(observation)
        reliability_failure = LiveFailureDetector().detect(
            observation,
            reliability_evaluation,
        )
        registration = (
            application_repository.get(
                context.tenant_id,
                context.application_id,
                context.environment,
            )
            if context is not None
            else None
        )
        context_verification_authorized = bool(
            registration and registration.context_verification_authorized
        )
        if context_verification_authorized:
            context_reason = (
                "no_context_available"
                if not retrieval.documents
                else "no_answer_available"
                if not answer
                else None
            )
            context_state = capability_state(
                "authorized",
                performed=bool(retrieval.documents and answer),
                reason=context_reason,
            )
        elif registration is None:
            context_state = capability_state(
                "not_applicable",
                performed=False,
                reason="application_not_registered",
            )
        else:
            context_state = capability_state(
                "not_authorized",
                performed=False,
                reason="application_not_authorized",
            )
        repair_state = (
            capability_state(
                "authorized",
                performed=False,
                reason="query_operation",
            )
            if registration and registration.repair_authorized
            else capability_state(
                "not_authorized",
                performed=False,
                reason="application_not_authorized",
            )
            if registration
            else capability_state(
                "not_applicable",
                performed=False,
                reason="application_not_registered",
            )
        )
        capability_results = capability_execution(
            context_verification=context_state,
            independent_verification=capability_state(
                "not_applicable",
                performed=False,
                reason="managed_index",
            ),
            repair=repair_state,
        )
        source_coverage = 1.0 if status == "grounded" else 0.0
        quality = {
            "term_match": round(min(1.0, score), 3),
            "source_coverage": source_coverage,
            "answer_relevancy": round(answer_relevancy(query, answer), 3),
            "faithfulness": (
                round(faithfulness(answer, retrieval), 3)
                if context_state["performed"]
                else None
            ),
        }
        if status == "no_match":
            answer = "I could not find a sufficiently relevant passage in the indexed documents to answer that question."
            quality["answer_relevancy"] = round(answer_relevancy(query, answer), 3)
            if context_state["performed"]:
                quality["faithfulness"] = round(faithfulness(answer, retrieval), 3)
        available_quality_scores = [
            value for value in quality.values()
            if isinstance(value, (int, float))
        ]
        quality["overall_quality"] = (
            round(sum(available_quality_scores) / len(available_quality_scores), 3)
            if available_quality_scores
            else None
        )
        run = {
            "id": f"run-{uuid4().hex[:8]}", "query": query, "status": status,
            "method": retrieval.retrieval_method.value, "latency_ms": latency_ms,
            "created_at": datetime.now(timezone.utc).isoformat(), "quality": quality,
            "capability_execution": capability_results,
            "tenant_id": context.tenant_id if context else "development",
            "application_id": context.application_id if context else "ragguard",
            "environment": context.environment if context else "development",
        }
        if record_run:
            self.runs.insert(0, run)
        if record_run and status == "no_match":
            failure = {"id": f"failure-{uuid4().hex[:8]}", "type": "NO_RETRIEVAL_MATCH", "severity": "high", "query": query, "status": "open", "evidence": ["No indexed chunk matched the query."], "created_at": run["created_at"], "tenant_id": run["tenant_id"], "application_id": run["application_id"], "environment": run["environment"]}
            self.failures.insert(0, failure)
        return {
            "answer": answer,
            "rag_status": status,
            "retrieval_quality": quality,
            "retrieval_method": retrieval.retrieval_method.value,
            "latency_ms": run["latency_ms"],
            "sources": [
                {
                    "chunk_id": chunk.chunk_id,
                    "document_id": chunk.document_id,
                    "source": chunk.metadata.get("source", chunk.document_id),
                    "section": chunk.metadata.get("section_title"),
                    "text": chunk.text,
                    "score": round(score, 4),
                }
                for chunk, score in zip(retrieval.documents, retrieval.scores)
            ],
            "reliability_evaluation": reliability_evaluation.model_dump(mode="json"),
            "reliability_failure": (
                reliability_failure.model_dump(mode="json")
                if reliability_failure is not None
                else None
            ),
            "application_id": observation.source.application_id,
            "environment": observation.source.environment,
            "knowledge_source": "managed_index",
            "metric_semantics": {
                "term_match": "lexical query-term overlap proxy; not a labeled relevance score",
                "source_coverage": "retrieval-threshold proxy; not answer citation coverage",
                "answer_relevancy": "local lexical similarity proxy; not a labeled relevance judgment",
                "faithfulness": "local context overlap proxy; not a semantic entailment check",
                "citation_accuracy": "default metric value; no citation verifier runs in this local workspace path",
                "overall_quality": "mean of available local proxy metrics",
                "embedding_model": "local TF-IDF retrieval model; not a neural embedding model",
            },
            "capability_execution": capability_results,
            "run": run,
        }

    @_workspace_locked
    def document_rows(self, context: TenantContext | None = None) -> list[dict]:
        self.refresh()
        chunks_by_document: dict[str, list] = {}
        for chunk in self.store.chunks:
            key = (chunk.metadata.get("ragguard_tenant_id"), chunk.metadata.get("application_id"), chunk.metadata.get("environment"), chunk.document_id)
            chunks_by_document.setdefault(key, []).append(chunk)
        namespace = context.vector_namespace if context else None
        vectorizer = self.store.vectorizers.get(namespace) if namespace else self.store.vectorizer
        dimensions = len(vectorizer.vocabulary_) if vectorizer is not None and hasattr(vectorizer, "vocabulary_") else 0
        rows = []
        for identity, document in self.documents.items():
            if context is not None and document.metadata.get("identity_scope_explicit") and identity[:3] != (context.tenant_id, context.application_id, context.environment):
                continue
            if namespace is not None and document.metadata.get("tenant_namespace") != namespace:
                continue
            chunks = chunks_by_document.get(identity, [])
            rows.append({
                "id": document.document_id,
                "source": document.metadata.get("source", document.document_id),
                "ingestion_method": document.metadata.get("ingestion_method", "directory"),
                "status": "indexed" if chunks else "no_chunks",
                "chunks": len(chunks),
                "characters": len(document.text),
                "embedding_model": "local-tfidf-lexical",
                "embedding_dimensions": dimensions,
                "embedding_vectors": len(chunks),
            })
        return rows

    @_workspace_locked
    def dashboard(self, context: TenantContext | None = None) -> dict:
        self.refresh()
        tenant_id = context.tenant_id if context else None
        runs = [
            run for run in self.runs
            if (tenant_id is None or run["tenant_id"] == tenant_id)
            and (context is None or run.get("application_id") == context.application_id)
            and (context is None or run.get("environment") == context.environment)
        ]
        failures_list = [
            failure for failure in self.failures
            if (tenant_id is None or failure["tenant_id"] == tenant_id)
            and (context is None or failure.get("application_id") == context.application_id)
            and (context is None or failure.get("environment") == context.environment)
        ]
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
        vectorizer = self.store.vectorizers.get(context.vector_namespace) if context else self.store.vectorizer
        dimensions = len(vectorizer.vocabulary_) if vectorizer is not None and hasattr(vectorizer, "vocabulary_") else 0
        return {"metrics": {**metric_defaults, **latest_quality, "failure_rate": round(failures / run_count, 3) if run_count else None, "repair_success_rate": None, "total_runs": run_count, "total_failures": failures}, "embedding": {"model": "local-tfidf-lexical", "dimension": dimensions, "vectors": len(chunks), "latency_ms": runs[0]["latency_ms"] if runs else None}, "index": {"documents": len(self.document_rows(context)), "chunks": len(chunks), "last_refresh": self.started_at.isoformat()}, "recent_failures": failures_list[:10]}


workspace = Workspace()
