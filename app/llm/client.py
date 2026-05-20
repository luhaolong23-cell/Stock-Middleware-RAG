from __future__ import annotations

import json
import logging
import re
from urllib import error, request

from app.core.config import settings
from app.llm.prompts import build_answer_messages, build_context
from app.retrieval.hybrid import ScoredChunk

logger = logging.getLogger(__name__)


class LLMClient:
    METRIC_TERMS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("营业收入", ("营业收入", "营业总收入")),
        ("总资产", ("总资产",)),
        ("股票代码", ("股票代码", "证券代码", "a股代码")),
        ("归母净利润", ("归属于上市公司股东的净利润", "归母净利润", "归属于本行股东的净利润")),
        ("净利润", ("净利润",)),
        ("总负债", ("总负债", "负债合计", "负债总额")),
        ("归母净资产", ("归属于上市公司股东的所有者权益", "归母净资产", "归属于本行股东的净资产")),
        ("经营活动现金流量净额", ("经营活动产生的现金流量净额", "经营活动现金流量净额")),
        ("基本每股收益", ("基本每股收益", "每股收益", "eps")),
    )

    def __init__(self) -> None:
        self.base_url = settings.llm_base_url.rstrip("/")
        self.api_key = settings.llm_api_key
        self.model = settings.llm_model
        self.timeout_seconds = settings.llm_timeout_seconds
        self.max_tokens = settings.llm_max_tokens
        self.temperature = settings.llm_temperature

    def generate(self, query: str, hits: list[ScoredChunk]) -> str:
        context = build_context(hits)
        if not context:
            return "没有可用证据。"

        if not self.is_configured():
            return self._fallback_summary(query, hits)

        messages = build_answer_messages(query, hits)
        try:
            answer = self._chat_completion(messages)
        except Exception as exc:
            logger.exception("llm generation failed: %s", exc)
            return self._fallback_summary(query, hits)

        return answer.strip() or self._fallback_summary(query, hits)

    def is_configured(self) -> bool:
        return bool(self.base_url and self.api_key and self.model)

    def supports_fallback_query(self, query: str) -> bool:
        metric_label, _metric_terms = self._resolve_metric_terms(query)
        return metric_label is not None

    def _chat_completion(self, messages: list[dict[str, str]]) -> str:
        endpoint = f"{self.base_url}/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        body = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        req = request.Request(endpoint, data=body, headers=headers, method="POST")
        try:
            with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                data = json.loads(resp.read().decode("utf-8"))
        except error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"LLM HTTP {exc.code}: {detail}") from exc

        choices = data.get("choices") or []
        if not choices:
            raise RuntimeError("LLM returned no choices")

        message = choices[0].get("message") or {}
        content = message.get("content")
        if isinstance(content, list):
            text_parts = [
                part.get("text", "")
                for part in content
                if isinstance(part, dict) and part.get("type") == "text"
            ]
            return "\n".join(part for part in text_parts if part)
        if isinstance(content, str):
            return content
        raise RuntimeError("LLM returned unsupported content format")

    def _fallback_summary(self, query: str, hits: list[ScoredChunk]) -> str:
        metric_label, metric_terms = self._resolve_metric_terms(query)
        reasons = []
        best_candidate: tuple[float, str, int] | None = None

        for index, hit in enumerate(hits[:3], start=1):
            title = hit.chunk.document.title
            snippet, value, confidence = self._extract_query_aware_snippet(
                content=hit.chunk.content,
                metric_label=metric_label,
                metric_terms=metric_terms,
            )
            if value:
                source_confidence = self._source_confidence(hit, metric_label)
                candidate = (
                    confidence + source_confidence,
                    source_confidence,
                    confidence,
                    value,
                    -index,
                )
                if best_candidate is None or candidate > best_candidate:
                    best_candidate = candidate
            reasons.append(f"- [{index}] {title}: {snippet}")

        if metric_label and best_candidate is not None:
            _score, _source_confidence, _confidence, extracted_value, extracted_source = (
                best_candidate
            )
            extracted_source = abs(extracted_source)
            conclusion = f"结论：根据[{extracted_source}]，{metric_label}为 {extracted_value}。"
        else:
            conclusion = f"结论：已基于检索到的文档为问题“{query}”整理出候选证据。"

        return "\n".join(
            [
                conclusion,
                "依据：",
                *reasons,
                "说明：当前未配置可用的 LLM 接口，返回的是证据摘要而不是模型生成答案。",
            ]
        )

    def _resolve_metric_terms(self, query: str) -> tuple[str | None, tuple[str, ...]]:
        normalized_query = self._normalize_text(query)
        for label, terms in self.METRIC_TERMS:
            if any(term.lower() in normalized_query for term in terms):
                return label, terms
        return None, ()

    def _extract_query_aware_snippet(
        self,
        content: str,
        metric_label: str | None,
        metric_terms: tuple[str, ...],
        radius: int = 90,
    ) -> tuple[str, str | None, float]:
        compact = re.sub(r"\s+", " ", content).strip()
        if not compact:
            return "", None, 0.0

        best_match: tuple[float, str, str] | None = None
        for term in metric_terms:
            lowered = compact.lower()
            position = lowered.find(term.lower())
            if position < 0:
                continue

            start = max(0, position - radius)
            end = min(len(compact), position + radius)
            snippet = compact[start:end].strip(" |")
            value, confidence = self._extract_value_after_term(
                text=compact,
                term=term,
                metric_label=metric_label,
            )
            candidate = (confidence, snippet[:220], value)
            if best_match is None or candidate > best_match:
                best_match = candidate

        if best_match is not None:
            confidence, snippet, value = best_match
            return snippet, value, confidence

        return compact[:220], None, 0.0

    def _extract_value_after_term(
        self,
        text: str,
        term: str,
        metric_label: str | None,
    ) -> tuple[str | None, float]:
        best_value: str | None = None
        best_score = 0.0
        lowered_lines = [line.strip() for line in text.splitlines() if line.strip()]
        compact_text = re.sub(r"\s+", " ", text).strip()
        if compact_text and compact_text not in lowered_lines:
            lowered_lines.append(compact_text)

        for line in lowered_lines:
            normalized_line = self._normalize_text(line)
            if term.lower() not in normalized_line:
                continue
            for value in re.findall(r"-?[0-9][0-9,]*(?:\.\d+)?", line):
                score = self._value_confidence(
                    line=line,
                    value=value,
                    metric_label=metric_label,
                    term=term,
                )
                if score > best_score:
                    best_value = value
                    best_score = score

        return best_value, best_score

    def _value_confidence(
        self,
        line: str,
        value: str,
        metric_label: str | None,
        term: str,
    ) -> float:
        score = 0.0
        normalized_line = self._normalize_text(line)
        normalized_term = self._normalize_text(term)
        normalized_value = value.replace(",", "")
        abs_value_text = normalized_value.lstrip("-")

        term_pos = normalized_line.find(normalized_term)
        value_pos = normalized_line.find(self._normalize_text(value))
        if term_pos >= 0 and value_pos > term_pos:
            score += 1.0

        if "," in value:
            score += 2.0
        if "." in value:
            score += 0.4
        if len(abs_value_text) >= 8:
            score += 1.2
        elif len(abs_value_text) >= 5:
            score += 0.6

        if any(token in normalized_line for token in ("本报告期", "本报告期末", "上年度末", "2026年第一季度", "2026年13月", "2026年3月31日")):
            score += 1.5
        if any(token in normalized_line for token in ("本报告期比上年同期", "增减变动幅度")):
            score += 0.5
        if any(token in normalized_line for token in ("项目|本报告期", "项目|2026年第一季度", "项目|2026年13月")):
            score += 1.0

        if "变动比例" in normalized_line or "主要原因" in normalized_line:
            score -= 2.2
        if "百分点" in normalized_line:
            score -= 1.8
        if value.startswith("-"):
            score -= 1.2

        if metric_label == "营业收入":
            if any(token in normalized_line for token in ("营业总收入", "其中营业收入", "本报告期", "上年同期")):
                score += 1.0
        if metric_label == "总资产":
            if any(token in normalized_line for token in ("总资产", "本报告期末", "上年度末", "期末")):
                score += 1.0

        return score

    def _source_confidence(self, hit: ScoredChunk, metric_label: str | None) -> float:
        section_title = hit.chunk.section_title or ""
        table_title = hit.chunk.table_title or ""
        combined = self._normalize_text("\n".join((section_title, table_title)))
        content = self._normalize_text(hit.chunk.content[:240])
        score = 0.0

        if hit.chunk.chunk_type == "table":
            score += 0.2
        if hit.chunk.page_number and hit.chunk.page_number <= 3:
            score += 0.4

        if any(token in combined for token in ("主要会计数据", "主要财务指标")):
            score += 2.8
        if any(token in combined for token in ("变动情况", "变动的情况", "主要原因")):
            score -= 2.4
        if any(token in content for token in ("变动比例", "主要原因")):
            score -= 1.4

        if metric_label == "营业收入":
            if "营业总收入" in content:
                score -= 0.4
            if "其中营业收入" in content:
                score -= 0.2
            if "本报告期" in content:
                score += 0.6
            if any(token in combined for token in ("利润表", "合并利润表")):
                score -= 0.8

        if metric_label == "总资产":
            if any(token in combined for token in ("资产负债表",)):
                score += 0.8
            if any(token in content for token in ("本报告期末", "上年度末", "期末")):
                score += 0.6

        return score

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", "", text).lower()
