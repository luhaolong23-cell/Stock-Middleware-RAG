from __future__ import annotations

import re
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.extractor import MetadataExtractor
from app.models.document import Document
from app.models.document_artifact import DocumentArtifact


class ArtifactService:
    ARTIFACT_VERSION = "v1"
    ANALYSIS_CONFIDENCE_THRESHOLD = 0.8
    METRIC_SPECS: tuple[dict[str, Any], ...] = (
        {
            "key": "revenue",
            "display_name": "营业收入",
            "terms": ("营业收入", "营业总收入"),
            "scope": "current_period",
            "amount_metric": True,
            "preferred_contexts": ("主要会计数据", "主要财务指标", "本报告期"),
            "forbidden_contexts": ("变动比例", "主要原因"),
        },
        {
            "key": "net_profit_attributable",
            "display_name": "归母净利润",
            "terms": (
                "归属于上市公司股东的净利润",
                "上市公司股东的净利润",
                "归属于母公司所有者的净利润",
                "归属于母公司股东的净利润",
                "母公司股东的净利润",
                "归属于本行股东的净利润",
                "本行股东的净利润",
                "归属于本行普通股股东的净利润",
                "本行普通股股东的净利润",
            ),
            "scope": "current_period",
            "amount_metric": True,
            "preferred_contexts": (
                "主要会计数据",
                "主要财务指标",
                "本报告期",
                "经营情况",
                "报告期内",
            ),
        },
        {
            "key": "net_profit",
            "display_name": "净利润",
            "terms": ("净利润",),
            "scope": "current_period",
            "amount_metric": True,
            "preferred_contexts": ("主要会计数据", "主要财务指标", "本报告期"),
            "forbidden_contexts": (
                "扣除非经常性损益",
                "归属于上市公司股东的净利润",
                "归属于母公司所有者的净利润",
                "归属于母公司股东的净利润",
                "归属于本行股东的净利润",
                "归属于本行普通股股东的净利润",
                "少数股东损益",
                "持续经营净利润",
                "终止经营净利润",
            ),
        },
        {
            "key": "total_assets",
            "display_name": "总资产",
            "terms": ("总资产", "资产总额", "资产总计", "资产合计"),
            "scope": "period_end",
            "amount_metric": True,
            "preferred_contexts": (
                "主要会计数据",
                "主要财务指标",
                "本报告期末",
                "上年度末",
                "经营情况",
                "资产负债表分析",
            ),
        },
        {
            "key": "total_liabilities",
            "display_name": "总负债",
            "terms": ("总负债", "负债合计", "负债总额"),
            "scope": "period_end",
            "amount_metric": True,
            "preferred_contexts": ("资产负债表", "负债合计", "所有者权益", "经营情况", "资产负债表分析"),
            "forbidden_contexts": ("递延所得税负债", "流动负债合计", "非流动负债合计", "期末现金及现金等价物余额"),
        },
        {
            "key": "equity_attributable",
            "display_name": "归母净资产",
            "terms": (
                "归属于上市公司股东的所有者权益",
                "上市公司股东的所有者权益",
                "归属于上市公司股东的净资产",
                "上市公司股东的净资产",
                "归属于母公司所有者权益",
                "归属于母公司股东权益",
                "母公司股东权益",
                "归属于本行股东权益",
                "本行股东权益",
                "归属于本行普通股股东的净资产",
                "本行股东的净资产",
            ),
            "scope": "period_end",
            "amount_metric": True,
            "preferred_contexts": (
                "主要会计数据",
                "主要财务指标",
                "本报告期末",
                "上年度末",
                "经营情况",
                "资产负债表分析",
            ),
            "forbidden_contexts": ("代理承销证券款",),
        },
        {
            "key": "operating_cash_flow",
            "display_name": "经营活动现金流净额",
            "terms": ("经营活动产生的现金流量净额",),
            "scope": "current_period",
            "amount_metric": True,
            "preferred_contexts": ("现金流量表", "2026年第一季度", "本报告期"),
        },
        {
            "key": "eps_basic",
            "display_name": "基本每股收益",
            "terms": ("基本每股收益",),
            "scope": "current_period",
            "amount_metric": False,
            "metric_unit": "元/股",
            "preferred_contexts": ("主要会计数据", "主要财务指标"),
        },
    )

    def __init__(self, db: Session) -> None:
        self.db = db
        self.metadata_extractor = MetadataExtractor()
        self._pdf_layout_cache: dict[str, list[tuple[int, str]]] = {}

    def generate_and_persist(self, document: Document) -> dict[str, dict[str, Any]]:
        if not document.industry:
            document.industry = self.metadata_extractor._extract_industry(
                document.title,
                document.raw_text,
            )
        basic_info = self._build_basic_info(document)
        facts_payload = self._build_extract_facts(document, basic_info)
        analysis_payload = self._build_analyze_fundamentals(facts_payload, basic_info)
        artifacts = {
            "extract_facts": facts_payload,
            "analyze_fundamentals": analysis_payload,
        }
        self._upsert_artifacts(document.id, artifacts)
        return artifacts

    def list_document_artifacts(self, document_id: int) -> list[dict[str, Any]]:
        stmt = (
            select(DocumentArtifact)
            .where(DocumentArtifact.document_id == document_id)
            .order_by(DocumentArtifact.artifact_type, DocumentArtifact.version.desc())
        )
        rows = self.db.scalars(stmt).all()
        return [
            {
                "artifact_type": row.artifact_type,
                "version": row.version,
                "status": row.status,
                "payload": row.payload,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]

    def _upsert_artifacts(self, document_id: int, artifacts: dict[str, dict[str, Any]]) -> None:
        stmt = select(DocumentArtifact).where(
            DocumentArtifact.document_id == document_id,
            DocumentArtifact.version == self.ARTIFACT_VERSION,
        )
        existing = {
            row.artifact_type: row
            for row in self.db.scalars(stmt).all()
        }
        for artifact_type, payload in artifacts.items():
            row = existing.get(artifact_type)
            if row is None:
                self.db.add(
                    DocumentArtifact(
                        document_id=document_id,
                        artifact_type=artifact_type,
                        version=self.ARTIFACT_VERSION,
                        status="ready",
                        payload=payload,
                    )
                )
                continue
            row.status = "ready"
            row.payload = payload
        self.db.commit()

    def _build_extract_facts(
        self,
        document: Document,
        basic_info: dict[str, Any],
    ) -> dict[str, Any]:
        metrics: dict[str, dict[str, Any] | None] = {}
        for spec in self.METRIC_SPECS:
            fact = self._extract_metric(document, basic_info, spec)
            metrics[spec["key"]] = fact
        self._apply_balance_sheet_consistency(metrics)
        facts = [
            metrics[spec["key"]]
            for spec in self.METRIC_SPECS
            if metrics.get(spec["key"]) is not None
        ]

        return {
            "node_type": "extract_facts",
            "schema_version": self.ARTIFACT_VERSION,
            "document_id": document.id,
            "company": basic_info["company"],
            "ticker": basic_info["ticker"],
            "report_period": basic_info["report_period"],
            "report_type": basic_info["report_type"],
            "basic_info": basic_info,
            "facts": facts,
            "metrics": metrics,
            "data_quality": {
                "fact_count": len(facts),
                "missing_metrics": [
                    spec["key"] for spec in self.METRIC_SPECS if metrics.get(spec["key"]) is None
                ],
                "derived_metrics": sorted(
                    [
                        key
                        for key, value in metrics.items()
                        if value is not None and value.get("fact_origin") == "derived"
                    ]
                ),
            },
        }

    def _build_analyze_fundamentals(
        self,
        facts_payload: dict[str, Any],
        basic_info: dict[str, Any],
    ) -> dict[str, Any]:
        metrics = facts_payload.get("metrics", {})
        ratios: dict[str, float] = {}
        signals: list[dict[str, Any]] = []
        low_confidence_metrics = sorted(
            [
                key
                for key, value in metrics.items()
                if value is not None
                and float(value.get("confidence", 0.0)) < self.ANALYSIS_CONFIDENCE_THRESHOLD
            ]
        )

        revenue = self._metric_amount(self._qualified_metric(metrics.get("revenue")))
        net_profit = self._metric_amount(
            self._qualified_metric(metrics.get("net_profit_attributable"))
        ) or self._metric_amount(self._qualified_metric(metrics.get("net_profit")))
        total_assets = self._metric_amount(self._qualified_metric(metrics.get("total_assets")))
        total_liabilities = self._metric_amount(
            self._qualified_metric(metrics.get("total_liabilities"))
        )
        equity = self._metric_amount(self._qualified_metric(metrics.get("equity_attributable")))
        operating_cash_flow = self._metric_amount(
            self._qualified_metric(metrics.get("operating_cash_flow"))
        )

        if revenue and net_profit is not None:
            ratios["net_margin"] = round(net_profit / revenue, 6)
            signals.append(
                {
                    "name": "profitability",
                    "value": "positive" if net_profit > 0 else "negative",
                    "detail": f"归母净利率约 {round((net_profit / revenue) * 100, 2)}%",
                }
            )
        if total_assets and total_liabilities is not None:
            ratios["debt_to_assets"] = round(total_liabilities / total_assets, 6)
            signals.append(
                {
                    "name": "leverage",
                    "value": "high" if total_liabilities / total_assets >= 0.6 else "moderate",
                    "detail": f"资产负债率约 {round((total_liabilities / total_assets) * 100, 2)}%",
                }
            )
        if revenue and operating_cash_flow is not None:
            ratios["operating_cashflow_margin"] = round(operating_cash_flow / revenue, 6)
            signals.append(
                {
                    "name": "cashflow",
                    "value": "positive" if operating_cash_flow > 0 else "negative",
                    "detail": f"经营现金流率约 {round((operating_cash_flow / revenue) * 100, 2)}%",
                }
            )
        if total_assets and equity is not None:
            ratios["equity_ratio"] = round(equity / total_assets, 6)

        available_metrics = {
            key: value
            for key, value in metrics.items()
            if value is not None
        }
        usable_raw_metrics = sorted(
            [
                key
                for key, value in metrics.items()
                if value is not None
                and value.get("fact_origin") == "raw_extracted"
                and float(value.get("confidence", 0.0)) >= self.ANALYSIS_CONFIDENCE_THRESHOLD
            ]
        )
        usable_derived_metrics = sorted(
            [
                key
                for key, value in metrics.items()
                if value is not None
                and value.get("fact_origin") == "derived"
                and float(value.get("confidence", 0.0)) >= self.ANALYSIS_CONFIDENCE_THRESHOLD
            ]
        )
        excluded_metrics = sorted(
            [
                key
                for key, value in metrics.items()
                if value is not None
                and float(value.get("confidence", 0.0)) < self.ANALYSIS_CONFIDENCE_THRESHOLD
            ]
        )
        return {
            "node_type": "analyze_fundamentals",
            "schema_version": self.ARTIFACT_VERSION,
            "document_id": facts_payload["document_id"],
            "company": basic_info["company"],
            "ticker": basic_info["ticker"],
            "report_period": basic_info["report_period"],
            "basic_info": basic_info,
            "snapshot": available_metrics,
            "ratios": ratios,
            "signals": signals,
            "usable_for_calc": {
                "raw_metrics": usable_raw_metrics,
                "derived_metrics": usable_derived_metrics,
                "excluded_metrics": excluded_metrics,
            },
            "data_quality": {
                "available_metric_count": len(available_metrics),
                "missing_metrics": facts_payload["data_quality"]["missing_metrics"],
                "low_confidence_metrics": low_confidence_metrics,
                "analysis_confidence_threshold": self.ANALYSIS_CONFIDENCE_THRESHOLD,
            },
            "summary": self._build_summary(
                signals,
                facts_payload["data_quality"]["missing_metrics"],
                low_confidence_metrics,
            ),
        }

    def _build_summary(
        self,
        signals: list[dict[str, Any]],
        missing_metrics: list[str],
        low_confidence_metrics: list[str],
    ) -> list[str]:
        summary = [signal["detail"] for signal in signals if signal.get("detail")]
        if missing_metrics:
            summary.append(f"仍缺少 {len(missing_metrics)} 项关键字段：{', '.join(missing_metrics)}")
        if low_confidence_metrics:
            summary.append(
                "以下字段已抽取但未进入分析计算："
                f"{', '.join(low_confidence_metrics)}"
            )
        if not summary:
            summary.append("当前只完成了基础字段归档，尚未形成足够的分析信号。")
        return summary

    def _build_basic_info(self, document: Document) -> dict[str, Any]:
        report_period, report_type = self._infer_report_period(document)
        currency, reported_unit = self._infer_currency_and_unit(document.raw_text)
        return {
            "document_id": document.id,
            "title": document.title,
            "source": document.source,
            "company": document.company,
            "ticker": document.ticker,
            "industry": document.industry,
            "published_at": document.published_at.isoformat() if document.published_at else None,
            "report_period": report_period,
            "report_type": report_type,
            "currency": currency,
            "reported_unit": reported_unit,
        }

    def _extract_metric(
        self,
        document: Document,
        basic_info: dict[str, Any],
        spec: dict[str, Any],
    ) -> dict[str, Any] | None:
        best_candidate: tuple[float, dict[str, Any]] | None = None
        candidates = []
        for chunk in document.chunks:
            for line, line_mode in self._candidate_lines(chunk.content):
                candidates.extend(
                    self._build_metric_candidates(
                        document=document,
                        basic_info=basic_info,
                        spec=spec,
                        chunk=chunk,
                        line=line,
                        line_mode=line_mode,
                    )
                )
        raw_text_chunk = SimpleNamespace(
            page_number=None,
            chunk_type="text",
            section_title="raw_text",
            table_title=None,
        )
        for line in document.raw_text.splitlines():
            line = line.strip()
            if not line:
                continue
            candidates.extend(
                self._build_metric_candidates(
                    document=document,
                    basic_info=basic_info,
                    spec=spec,
                    chunk=raw_text_chunk,
                    line=line,
                    line_mode="raw_text",
                )
            )
        for page_number, line in self._pdf_layout_lines(document):
            pdf_chunk = SimpleNamespace(
                page_number=page_number,
                chunk_type="pdf_layout",
                section_title="pdf_layout",
                table_title=None,
            )
            candidates.extend(
                self._build_metric_candidates(
                    document=document,
                    basic_info=basic_info,
                    spec=spec,
                    chunk=pdf_chunk,
                    line=line,
                    line_mode="pdf_layout",
                )
            )
        for score, fact in candidates:
            if best_candidate is None or score > best_candidate[0]:
                best_candidate = (score, fact)
        return best_candidate[1] if best_candidate is not None else None

    def _build_metric_candidates(
        self,
        document: Document,
        basic_info: dict[str, Any],
        spec: dict[str, Any],
        chunk: Any,
        line: str,
        line_mode: str,
    ) -> list[tuple[float, dict[str, Any]]]:
        candidates: list[tuple[float, dict[str, Any]]] = []
        for term in spec["terms"]:
            normalized_line = self._normalize_text(line)
            normalized_term = self._normalize_text(term)
            if not self._line_matches_term(line, term, normalized_line, normalized_term):
                continue
            if spec["key"] == "eps_basic" and "|" not in line and line_mode != "raw_text":
                continue
            if spec.get("amount_metric", True) and "|" not in line and line_mode == "raw":
                continue
            if line_mode == "raw_text" and not self._looks_like_statement_row(line, normalized_term):
                continue
            start_at = self._find_term_start(line, term, normalized_line, normalized_term)
            if start_at is None:
                continue
            value_source = line[start_at:]
            raw_values = self._extract_numeric_tokens(value_source)
            if not raw_values:
                continue
            raw_values = self._strip_leading_footnote_numbers(value_source, raw_values)
            if spec["key"] == "eps_basic":
                raw_values = self._strip_eps_footnote_numbers(value_source, term, raw_values)
                if not raw_values:
                    continue
            if (spec.get("amount_metric", True) or spec["key"] == "eps_basic") and len(raw_values) < 2:
                continue
            current_value = raw_values[0]
            previous_value = raw_values[1] if len(raw_values) > 1 else None
            change_pct = self._guess_change_pct(raw_values[2:]) if len(raw_values) > 2 else None
            numeric_value = self._to_number(current_value)
            if numeric_value is None:
                continue
            score = self._score_candidate(
                chunk,
                line,
                term,
                spec,
                line_mode,
                normalized_line=normalized_line,
                normalized_term=normalized_term,
            )
            fact = {
                "metric": spec["key"],
                "display_name": spec["display_name"],
                "fact_origin": "raw_extracted",
                "term": term,
                "value": current_value,
                "numeric_value": numeric_value,
                "previous_value": previous_value,
                "previous_numeric_value": self._to_number(previous_value),
                "change_pct": change_pct,
                "reported_unit": spec.get("metric_unit") or basic_info["reported_unit"],
                "currency": basic_info["currency"],
                "normalized_value_cny": self._normalize_amount(
                    numeric_value,
                    basic_info["reported_unit"],
                    spec["amount_metric"],
                ),
                "scope": spec["scope"],
                "source_page": chunk.page_number,
                "citation_title": document.title,
                "section_title": chunk.section_title,
                "table_title": chunk.table_title,
                "confidence": round(self._confidence(score), 4),
            }
            candidates.append((score, fact))
        return candidates

    def _candidate_lines(self, content: str) -> list[tuple[str, str]]:
        lines = [line.strip() for line in content.splitlines() if line.strip()]
        return [(line, "raw") for line in lines]

    def _score_candidate(
        self,
        chunk,
        line: str,
        term: str,
        spec: dict[str, Any],
        line_mode: str,
        normalized_line: str,
        normalized_term: str,
    ) -> float:
        combined = self._normalize_text(
            "\n".join(
                part
                for part in (
                    chunk.section_title or "",
                    chunk.table_title or "",
                    line,
                )
                if part
            )
        )
        score = 0.0
        if chunk.chunk_type == "table":
            score += 1.2
        if chunk.page_number and chunk.page_number <= 3:
            score += 0.6
        if line_mode == "raw":
            score += 1.5
        elif line_mode == "raw_text":
            score += 3.0
        elif line_mode == "pdf_layout":
            score += 4.0
        else:
            score -= 0.3
        if any(token in combined for token in ("主要会计数据", "主要财务指标")):
            score += 3.2
        if any(token in combined for token in ("变动情况", "变动的情况", "主要原因", "变动比例")):
            score -= 2.6
        if normalized_line.startswith(normalized_term):
            score += 1.6
        term_pos = normalized_line.find(normalized_term)
        if term_pos >= 0 and term_pos <= 6:
            score += 0.8
        if line_mode == "pdf_layout" and normalized_line.startswith(normalized_term):
            score += 2.2
        if (
            spec["key"] != "eps_basic"
            and chunk.page_number is not None
            and chunk.page_number <= 3
            and any(marker in line for marker in (f"{term}(", f"{term}（"))
        ):
            score -= 4.0

        if spec["scope"] == "current_period":
            if "本报告期" in combined:
                score += 1.0
        if spec["scope"] == "period_end":
            if any(token in combined for token in ("本报告期末", "上年度末", "期末")):
                score += 1.2
            if "资产负债表" in combined:
                score += 0.6

        score += self._statement_context_bonus(spec["key"], combined)

        for token in spec.get("preferred_contexts", ()):
            if token and token in combined:
                score += 1.0
        for token in spec.get("forbidden_contexts", ()):
            if token and token in combined:
                score -= 2.0

        if spec["key"] == "revenue" and "其中营业收入" in combined:
            score -= 0.3
        if spec["key"] == "revenue" and any(
            token in combined
            for token in (
                "利息净收入比营业收入",
                "非利息净收入比营业收入",
                "手续费及佣金净收入比营业收入",
            )
        ):
            score -= 4.0
        if spec["key"] == "net_profit" and "归属于上市公司股东的净利润" in combined:
            score -= 0.4
        if spec["key"] == "net_profit" and "扣除非经常性损益" in combined:
            score -= 4.0
        if spec["key"] == "net_profit" and any(
            token in normalized_line
            for token in ("五、净利润", "四、净利润", "净利润（", "净利润(")
        ):
            score += 5.0
        if spec["key"] == "net_profit" and normalized_line.startswith("净利润"):
            score += 4.0
        if spec["key"] == "net_profit" and "归属于" in normalized_line:
            score -= 4.0
        if spec["key"] == "eps_basic" and len(re.findall(r"-?[0-9][0-9,]*(?:\.\d+)?", line)) <= 1:
            score -= 2.5
        return score

    def _statement_context_bonus(self, metric_key: str, combined: str) -> float:
        if metric_key in {"revenue", "net_profit", "net_profit_attributable"}:
            if any(token in combined for token in ("合并利润表", "利润表")):
                return 4.2
        if metric_key in {"total_assets", "total_liabilities", "equity_attributable"}:
            if any(token in combined for token in ("合并资产负债表", "资产负债表")):
                return 4.2
        if metric_key == "operating_cash_flow":
            if any(token in combined for token in ("合并现金流量表", "现金流量表")):
                return 4.2
        return 0.0

    def _apply_balance_sheet_consistency(
        self,
        metrics: dict[str, dict[str, Any] | None],
    ) -> None:
        total_assets = metrics.get("total_assets")
        total_liabilities = metrics.get("total_liabilities")
        equity = metrics.get("equity_attributable")
        assets_amount = self._metric_amount(total_assets)
        liabilities_amount = self._metric_amount(total_liabilities)
        equity_amount = self._metric_amount(equity)
        if not assets_amount:
            return

        if (
            liabilities_amount is not None
            and equity_amount is not None
            and liabilities_amount > assets_amount * 1.2
            and self._is_summary_metric(total_assets)
            and self._is_summary_metric(equity)
        ):
            derived_liabilities = max(assets_amount - equity_amount, 0.0)
            metrics["total_liabilities"] = self._build_derived_metric(
                base_metric=total_assets,
                metric_key="total_liabilities",
                display_name="总负债",
                normalized_value=derived_liabilities,
            )
            total_liabilities = metrics["total_liabilities"]
            liabilities_amount = derived_liabilities

        if liabilities_amount is not None and liabilities_amount > assets_amount * 1.2:
            self._downgrade_metric(
                total_liabilities,
                "balance_sheet_inconsistent",
                abs(liabilities_amount - assets_amount) / max(assets_amount, 1.0),
            )
        if liabilities_amount is not None and equity_amount is not None:
            gap = abs((liabilities_amount + equity_amount) - assets_amount) / max(assets_amount, 1.0)
            if gap > 0.35:
                self._downgrade_metric(total_liabilities, "balance_sheet_gap", gap)
                self._downgrade_metric(equity, "balance_sheet_gap", gap)

    def _downgrade_metric(
        self,
        metric: dict[str, Any] | None,
        quality_flag: str,
        gap: float,
    ) -> None:
        if not metric:
            return
        if metric.get("fact_origin") == "raw_extracted":
            metric["fact_origin"] = "downgraded_raw"
        metric["confidence"] = round(min(float(metric.get("confidence", 0.0)), 0.49), 4)
        metric["quality_flag"] = quality_flag
        metric["consistency_gap"] = round(gap, 6)

    def _build_derived_metric(
        self,
        base_metric: dict[str, Any] | None,
        metric_key: str,
        display_name: str,
        normalized_value: float,
    ) -> dict[str, Any] | None:
        if not base_metric:
            return None
        reported_unit = base_metric.get("reported_unit")
        divisor = self._unit_multiplier(reported_unit)
        raw_value = normalized_value / divisor if divisor else normalized_value
        return {
            "metric": metric_key,
            "display_name": display_name,
            "fact_origin": "derived",
            "term": "derived",
            "value": self._format_numeric_value(raw_value),
            "numeric_value": raw_value,
            "previous_value": None,
            "previous_numeric_value": None,
            "change_pct": None,
            "reported_unit": reported_unit,
            "currency": base_metric.get("currency"),
            "normalized_value_cny": round(normalized_value, 4),
            "scope": base_metric.get("scope"),
            "source_page": base_metric.get("source_page"),
            "citation_title": base_metric.get("citation_title"),
            "section_title": base_metric.get("section_title"),
            "table_title": base_metric.get("table_title"),
            "confidence": 0.88,
            "quality_flag": "derived_from_assets_minus_equity",
        }

    def _pdf_layout_lines(self, document: Document) -> list[tuple[int, str]]:
        cached = self._pdf_layout_cache.get(document.source)
        if cached is not None:
            return cached
        path = Path(document.source)
        if not path.exists():
            self._pdf_layout_cache[document.source] = []
            return []
        try:
            result = subprocess.run(
                ["pdftotext", "-layout", str(path), "-"],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except (OSError, subprocess.SubprocessError):
            self._pdf_layout_cache[document.source] = []
            return []

        lines: list[tuple[int, str]] = []
        for page_number, page in enumerate(result.stdout.split("\f"), start=1):
            page_lines = [line.strip() for line in page.splitlines() if line.strip()]
            for index, stripped in enumerate(page_lines):
                if stripped:
                    lines.append((page_number, stripped))
                if index + 1 < len(page_lines):
                    merged = f"{stripped} {page_lines[index + 1]}".strip()
                    if merged and len(merged) <= 180:
                        lines.append((page_number, merged))
        self._pdf_layout_cache[document.source] = lines
        return lines

    def _format_numeric_value(self, value: float) -> str:
        text = f"{value:,.2f}"
        if text.endswith(".00"):
            return text[:-3]
        return text

    def _is_summary_metric(self, metric: dict[str, Any] | None) -> bool:
        if not metric:
            return False
        section = self._normalize_text(metric.get("section_title") or "")
        table = self._normalize_text(metric.get("table_title") or "")
        page = metric.get("source_page")
        return (
            (page is not None and int(page) <= 3)
            and (
                "主要会计数据" in section
                or "主要财务指标" in section
                or "主要会计数据" in table
                or "主要财务指标" in table
            )
        )

    def _strip_eps_footnote_numbers(
        self,
        value_source: str,
        term: str,
        raw_values: list[str],
    ) -> list[str]:
        trimmed = value_source.strip()
        if not trimmed.startswith(term) or not raw_values:
            return raw_values
        suffix = trimmed[len(term) :].lstrip()
        if not suffix:
            return raw_values
        first = raw_values[0]
        if first in {"(1)", "（1）", "(2)", "（2）", "(3)", "（3）", "(4)", "（4）"}:
            return raw_values[1:]
        if first.isdigit() and int(first) <= 9 and suffix.startswith(first):
            return raw_values[1:]
        return raw_values

    def _strip_leading_footnote_numbers(
        self,
        value_source: str,
        raw_values: list[str],
    ) -> list[str]:
        if not raw_values:
            return raw_values
        trimmed = value_source.strip()
        first = raw_values[0]
        if first in {"(1)", "（1）", "(2)", "（2）", "(3)", "（3）", "(4)", "（4）"}:
            return raw_values[1:]
        if first.isdigit() and int(first) <= 9:
            footnote_forms = (
                f"({first})",
                f"（{first}）",
                f"{first}（",
                f"{first}(",
            )
            if any(trimmed.startswith(form) for form in footnote_forms):
                return raw_values[1:]
        return raw_values

    def _find_term_start(
        self,
        line: str,
        term: str,
        normalized_line: str,
        normalized_term: str,
    ) -> int | None:
        direct = line.find(term)
        if direct >= 0:
            return direct
        normalized_pos = normalized_line.find(normalized_term)
        if normalized_pos < 0:
            return None

        normalized_index = 0
        start_index: int | None = None
        for raw_index, char in enumerate(line):
            if char.isspace():
                continue
            if normalized_index == normalized_pos:
                start_index = raw_index
                break
            normalized_index += 1
        return start_index

    def _line_matches_term(
        self,
        line: str,
        term: str,
        normalized_line: str,
        normalized_term: str,
    ) -> bool:
        if term not in line and normalized_term not in normalized_line:
            return False
        if normalized_term != "净利润":
            if normalized_term == "营业收入" and any(
                token in normalized_line
                for token in (
                    "比营业收入",
                    "其中营业收入",
                )
            ):
                return False
            return True
        if any(
            token in normalized_line
            for token in (
                "扣除非经常性损益",
                "归属于上市公司股东的净利润",
                "归属于母公司所有者的净利润",
                "归属于母公司股东的净利润",
                "归属于本行股东的净利润",
                "归属于本行普通股股东的净利润",
                "影响本行股东净利润",
                "影响少数股东净利润",
            )
        ):
            return False
        return True

    def _looks_like_statement_row(self, line: str, normalized_term: str) -> bool:
        normalized_line = self._normalize_text(line)
        term_pos = normalized_line.find(normalized_term)
        if term_pos < 0 or term_pos > 12:
            return False
        if len(line) > 140:
            return False
        numeric_tokens = self._extract_numeric_tokens(line)
        if len(numeric_tokens) < 2:
            return False
        if "|" in line:
            return True
        if re.search(r"\s{2,}", line):
            return True
        return normalized_line.startswith(normalized_term) or "、" in line[:8]

    def _extract_numeric_tokens(self, text: str) -> list[str]:
        return re.findall(
            r"[\(（]-?[0-9][0-9,]*(?:\.\d+)?[\)）]|-?[0-9][0-9,]*(?:\.\d+)?",
            text,
        )

    def _confidence(self, score: float) -> float:
        return min(0.99, max(0.35, 0.45 + score / 10))

    def _metric_amount(self, metric: dict[str, Any] | None) -> float | None:
        if not metric:
            return None
        normalized = metric.get("normalized_value_cny")
        if normalized is not None:
            return float(normalized)
        numeric_value = metric.get("numeric_value")
        return float(numeric_value) if numeric_value is not None else None

    def _qualified_metric(self, metric: dict[str, Any] | None) -> dict[str, Any] | None:
        if not metric:
            return None
        if float(metric.get("confidence", 0.0)) < self.ANALYSIS_CONFIDENCE_THRESHOLD:
            return None
        return metric

    def _normalize_amount(
        self,
        value: float,
        reported_unit: str | None,
        amount_metric: bool,
    ) -> float | None:
        if not amount_metric:
            return None
        multiplier = self._unit_multiplier(reported_unit)
        return round(value * multiplier, 4)

    def _unit_multiplier(self, reported_unit: str | None) -> float:
        if not reported_unit:
            return 1.0
        compact = reported_unit.replace(" ", "")
        if "百万元" in compact:
            return 1_000_000.0
        if "亿元" in compact:
            return 100_000_000.0
        if "万元" in compact:
            return 10_000.0
        if "千元" in compact:
            return 1_000.0
        return 1.0

    def _infer_currency_and_unit(self, raw_text: str) -> tuple[str | None, str | None]:
        search_window = raw_text[:50000]
        head = raw_text[:5000]
        unit_match = re.search(r"单位[:：]\s*([^\n；;。]{1,30})", head)
        currency_match = re.search(r"币种[:：]\s*([^\n；;。]{1,20})", head)
        if currency_match and "人民币" in currency_match.group(1):
            currency = "CNY"
        elif "人民币百万元" in search_window:
            currency = "CNY"
        elif "人民币" in search_window:
            currency = "CNY"
        else:
            currency = None

        unit = unit_match.group(1).strip() if unit_match else None
        if not unit:
            if "人民币百万元" in search_window:
                unit = "人民币百万元"
            elif "百万元" in search_window:
                unit = "百万元"
            elif re.search(r"单位[:：]\s*万元", search_window):
                unit = "万元"
            elif re.search(r"单位[:：]\s*亿元", search_window):
                unit = "亿元"
            elif re.search(r"单位[:：]\s*元", search_window):
                unit = "元"
        return currency, unit

    def _infer_report_period(self, document: Document) -> tuple[str | None, str]:
        haystack = f"{document.title} {document.source}"
        year_match = re.search(r"(20\d{2})", haystack)
        year = year_match.group(1) if year_match else None
        lowered = haystack.lower()
        if "q1" in lowered or "一季报" in haystack or "第一季度" in haystack:
            return (f"{year}Q1" if year else None, "quarterly")
        if "q3" in lowered or "三季报" in haystack or "第三季度" in haystack:
            return (f"{year}Q3" if year else None, "quarterly")
        if "半年报" in haystack or "半年度报告" in haystack:
            return (f"{year}H1" if year else None, "semiannual")
        if "年报" in haystack or "年度报告" in haystack:
            return (f"{year}FY" if year else None, "annual")
        return (year, "unknown")

    def _guess_change_pct(self, candidates: list[str]) -> float | None:
        for raw in candidates:
            value = self._to_number(raw)
            if value is None:
                continue
            if abs(value) <= 1000:
                return value
        return None

    def _to_number(self, value: str | None) -> float | None:
        if value is None:
            return None
        compact = value.replace(",", "").strip()
        if not compact:
            return None
        negative = False
        if (compact.startswith("(") and compact.endswith(")")) or (
            compact.startswith("（") and compact.endswith("）")
        ):
            negative = True
            compact = compact[1:-1].strip()
        try:
            numeric = float(compact)
            return -numeric if negative else numeric
        except ValueError:
            return None

    def _normalize_text(self, text: str) -> str:
        return re.sub(r"\s+", "", text).lower()
