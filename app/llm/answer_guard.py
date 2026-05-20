from __future__ import annotations

from app.core.config import settings
from app.retrieval.hybrid import ScoredChunk


class AnswerGuard:
    def can_answer(self, hits: list[ScoredChunk]) -> bool:
        return bool(hits) and hits[0].score >= settings.min_answer_score

    def refusal_message(self) -> str:
        return "当前知识库中没有足够证据支持回答这个问题，请补充更具体的公司、时间或文档范围。"

    def unsupported_question_message(self) -> str:
        return (
            "当前服务未配置可用的 LLM，只支持财报中的基础指标与结构化事实问答。"
            "像董事长、管理层职责或开放式分析问题暂不直接回答。"
        )

    def build_citations(self, hits: list[ScoredChunk], limit: int = 3) -> list[dict]:
        citations = []
        for hit in hits[:limit]:
            chunk = hit.chunk
            citations.append(
                {
                    "document_id": chunk.document_id,
                    "title": chunk.document.title,
                    "source": chunk.document.source,
                    "doc_type": chunk.document.doc_type,
                    "chunk_type": chunk.chunk_type,
                    "section_title": chunk.section_title,
                    "page_number": chunk.page_number,
                    "table_title": chunk.table_title,
                    "figure_title": chunk.figure_title,
                    "published_at": chunk.document.published_at,
                    "snippet": chunk.content[:240],
                    "score": round(hit.score, 4),
                }
            )
        return citations
