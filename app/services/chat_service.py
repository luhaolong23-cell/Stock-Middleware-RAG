from __future__ import annotations

import time
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.config import settings
from app.llm.answer_guard import AnswerGuard
from app.llm.client import LLMClient
from app.models.query_log import QueryLog
from app.services.retrieval_service import RetrievalService


class ChatService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.retrieval = RetrievalService(db)
        self.guard = AnswerGuard()
        self.llm = LLMClient()

    def answer(
        self,
        query: str,
        top_k: int = 5,
        log_query: bool = True,
        request_tag: str = "interactive",
    ) -> dict:
        start = time.perf_counter()
        rewritten_query = self.rewrite_query(query)
        hits = self.retrieval.retrieve(rewritten_query, top_k=top_k)
        guard_passed = self.guard.can_answer(hits)
        llm_configured = self.llm.is_configured()
        fallback_supported = self.llm.supports_fallback_query(query)
        refusal_reason: str | None = None

        if guard_passed and (llm_configured or fallback_supported):
            answer = self.llm.generate(query, hits)
            citations = self.guard.build_citations(hits, limit=top_k)
        elif guard_passed:
            answer = self.guard.unsupported_question_message()
            citations = []
            refusal_reason = "unsupported_query_without_llm"
        else:
            answer = self.guard.refusal_message()
            citations = []
            refusal_reason = "insufficient_evidence"

        latency_ms = int((time.perf_counter() - start) * 1000)
        if log_query:
            self._log_query(
                query=query,
                rewritten_query=rewritten_query,
                answer=answer,
                hits=hits,
                citations=citations,
                latency_ms=latency_ms,
                top_k=top_k,
                guard_passed=guard_passed,
                refusal_reason=refusal_reason,
                request_tag=request_tag,
            )

        return {
            "query": query,
            "rewritten_query": rewritten_query,
            "answer": answer,
            "citations": citations,
        }

    def rewrite_query(self, query: str) -> str:
        return " ".join(query.strip().split())

    def _log_query(
        self,
        query: str,
        rewritten_query: str,
        answer: str,
        hits: list[Any],
        citations: list[dict],
        latency_ms: int,
        top_k: int,
        guard_passed: bool,
        refusal_reason: str | None,
        request_tag: str,
    ) -> None:
        record = QueryLog(
            query=query,
            rewritten_query=rewritten_query,
            answer=answer,
            sources=self._make_json_safe(
                {
                    "request_tag": request_tag,
                    "top_k": top_k,
                    "guard_passed": guard_passed,
                    "refusal_reason": refusal_reason,
                    "answer_mode": self._detect_answer_mode(answer, guard_passed),
                    "citations": citations,
                    "retrieval_hits": self._serialize_hits(hits),
                    "runtime_config": self._runtime_config(),
                }
            ),
            latency_ms=latency_ms,
        )
        self.db.add(record)
        self.db.commit()

    def _serialize_hits(self, hits: list[Any], limit: int = 8) -> list[dict[str, Any]]:
        serialized: list[dict[str, Any]] = []
        for hit in hits[:limit]:
            chunk = hit.chunk
            serialized.append(
                {
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "title": chunk.document.title,
                    "source": chunk.document.source,
                    "chunk_type": chunk.chunk_type,
                    "page_number": chunk.page_number,
                    "section_title": chunk.section_title,
                    "table_title": chunk.table_title,
                    "figure_title": chunk.figure_title,
                    "score": round(float(hit.score), 4),
                    "reasons": list(hit.reasons),
                    "snippet": chunk.content[:240],
                }
            )
        return serialized

    def _runtime_config(self) -> dict[str, Any]:
        dialect = getattr(getattr(self.db, "bind", None), "dialect", None)
        return {
            "database_backend": getattr(dialect, "name", "unknown"),
            "embedding_model": settings.embedding_model,
            "embedding_dimensions": settings.embedding_dimensions,
            "llm_model": settings.llm_model,
        }

    def _detect_answer_mode(self, answer: str, guard_passed: bool) -> str:
        if not guard_passed:
            return "refusal"
        if "当前未配置可用的 LLM 接口" in answer:
            return "fallback_summary"
        return "llm"

    def _make_json_safe(self, payload: Any) -> Any:
        if isinstance(payload, datetime):
            return payload.isoformat()
        if isinstance(payload, dict):
            return {key: self._make_json_safe(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._make_json_safe(item) for item in payload]
        return payload
