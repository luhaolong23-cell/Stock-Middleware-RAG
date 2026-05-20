from __future__ import annotations

import re

from app.retrieval.embedder import simple_tokenize
from app.retrieval.hybrid import ScoredChunk


class SimpleReranker:
    STATEMENT_INTENTS = (
        (
            ("资产负债表",),
            ("资产负债表", "合并资产负债表"),
            2.2,
            0.8,
        ),
        (
            ("利润表",),
            ("利润表", "合并利润表"),
            2.2,
            0.8,
        ),
        (
            ("现金流量表",),
            ("现金流量表", "合并现金流量表"),
            2.2,
            0.8,
        ),
        (
            ("主要会计数据", "主要财务指标"),
            ("主要会计数据", "主要财务指标"),
            2.0,
            0.6,
        ),
    )

    def rank(self, query: str, hits: list[ScoredChunk], top_k: int = 5) -> list[ScoredChunk]:
        query_tokens = set(simple_tokenize(query))
        reranked: list[ScoredChunk] = []
        normalized_query = self._normalize(query)

        for hit in hits:
            document = hit.chunk.document
            text = "\n".join(
                [
                    document.title if document else "",
                    document.company if document and document.company else "",
                    document.ticker if document and document.ticker else "",
                    hit.chunk.section_title or "",
                    hit.chunk.table_title or "",
                    hit.chunk.figure_title or "",
                    hit.chunk.content,
                ]
            )
            tokens = set(simple_tokenize(text))
            coverage = len(query_tokens & tokens) / max(len(query_tokens), 1)
            score = hit.score + coverage
            if hit.chunk.section_title:
                score += 0.1

            score += self._intent_boost(normalized_query, hit)
            reranked.append(
                ScoredChunk(
                    chunk=hit.chunk,
                    score=score,
                    reasons=[*hit.reasons, "coverage_rerank"],
                )
            )

        return sorted(reranked, key=lambda item: item.score, reverse=True)[:top_k]

    def _intent_boost(self, query: str, hit: ScoredChunk) -> float:
        chunk = hit.chunk
        content = chunk.content
        normalized_content = self._normalize(content)
        title_text = " ".join(
            part
            for part in (
                chunk.section_title,
                chunk.table_title,
                chunk.figure_title,
                chunk.document.title if chunk.document else None,
                chunk.document.company if chunk.document else None,
                chunk.document.ticker if chunk.document else None,
            )
            if part
        )
        normalized_title = self._normalize(title_text)
        boost = 0.0

        if chunk.chunk_type == "image":
            boost -= 1.0

        if any(term in query for term in ("股票代码", "证券代码", "a股代码")):
            if self._contains_any(
                normalized_content,
                ("股票代码", "证券代码", "a股代码", "a股简称", "证券简称"),
            ):
                boost += 2.2
            if self._contains_any(
                normalized_title,
                ("股票简况", "基本情况", "公司信息", "重要提示", "证券代码", "证券简称"),
            ):
                boost += 1.2
            if chunk.page_number and chunk.page_number <= 2:
                boost += 1.0
            if chunk.chunk_type == "table":
                boost += 0.4
            if self._contains_any(
                normalized_title + normalized_content,
                ("股东信息", "前10名股东", "优先股", "流动性覆盖率"),
            ):
                boost -= 1.4
            if not self._contains_any(
                normalized_content,
                ("股票代码", "证券代码", "a股代码", "600", "601", "000", "001", "300"),
            ):
                boost -= 0.8

        if "营业收入" in query:
            if self._contains_any(normalized_content, ("营业收入", "营业总收入")):
                boost += 1.8
                boost += self._keyword_position_boost(
                    normalized_content,
                    ("营业收入", "营业总收入"),
                )
            if self._contains_any(
                normalized_title,
                ("主要会计数据", "主要财务指标", "合并利润表", "季度财务报表"),
            ):
                boost += 0.9
            if self._contains_any(
                normalized_content,
                ("本报告期", "上年同期", "本报告期比上年同期"),
            ):
                boost += 0.8
            if chunk.chunk_type == "table":
                boost += 0.7
            if chunk.chunk_type == "text":
                boost -= 0.5
            if self._contains_any(normalized_content, ("营业收入构成", "占营业收入", "营业收入比")):
                boost -= 1.1

        if "总资产" in query:
            if "总资产" in normalized_content:
                boost += 1.8
                boost += self._keyword_position_boost(
                    normalized_content,
                    ("总资产",),
                )
            if self._contains_any(
                normalized_title,
                ("主要会计数据", "主要财务指标", "合并资产负债表", "季度财务报表"),
            ):
                boost += 1.0
            if self._contains_any(
                normalized_content,
                ("本报告期末", "上年度末", "期末", "年度末", "本报告期末比上年度末"),
            ):
                boost += 1.1
            if chunk.chunk_type == "table":
                boost += 0.8
            if chunk.chunk_type == "text":
                boost -= 0.7
            if self._contains_any(normalized_title + normalized_content, ("投资组合", "股东信息", "保险资金")):
                boost -= 1.0
            if self._contains_any(
                normalized_title,
                ("主要会计数据", "主要财务指标"),
            ) and self._contains_any(
                normalized_content,
                ("总资产", "归属于上市公司股东的所有者权益"),
            ):
                boost += 0.9

        boost += self._statement_intent_boost(query, chunk.chunk_type, normalized_title, normalized_content)

        if chunk.document:
            for candidate in (
                chunk.document.company or "",
                chunk.document.ticker or "",
            ):
                candidate = candidate.strip()
                if candidate and candidate in query:
                    boost += 0.8

        return boost

    def _normalize(self, text: str) -> str:
        return re.sub(r"\s+", "", text).lower()

    def _contains_any(self, haystack: str, needles: tuple[str, ...]) -> bool:
        return any(needle.lower() in haystack for needle in needles)

    def _keyword_position_boost(self, haystack: str, needles: tuple[str, ...]) -> float:
        positions = [
            haystack.find(needle.lower())
            for needle in needles
            if needle and haystack.find(needle.lower()) >= 0
        ]
        if not positions:
            return 0.0

        first_pos = min(positions)
        if first_pos <= 40:
            return 1.2
        if first_pos <= 120:
            return 0.8
        if first_pos <= 240:
            return 0.4
        return 0.1

    def _statement_intent_boost(
        self,
        query: str,
        chunk_type: str,
        normalized_title: str,
        normalized_content: str,
    ) -> float:
        boost = 0.0
        matched = False

        for query_terms, target_terms, title_boost, content_boost in self.STATEMENT_INTENTS:
            if not any(term in query for term in query_terms):
                continue
            matched = True
            if self._contains_any(normalized_title, target_terms):
                boost += title_boost
            if self._contains_any(normalized_content, target_terms):
                boost += content_boost

        if not matched:
            return boost

        if chunk_type == "table":
            boost += 0.9
        elif chunk_type == "text":
            boost -= 0.4

        return boost
