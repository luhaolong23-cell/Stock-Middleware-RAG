from __future__ import annotations

import argparse
import csv
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.models.document import Document


ATTRIBUTABLE_TERMS = (
    "归属于上市公司股东的净利润",
    "归属于母公司股东的净利润",
    "归属于母公司所有者的净利润",
    "归属于本行股东的净利润",
    "归属于本行普通股股东的净利润",
)

EQUITY_TERMS = (
    "归属于上市公司股东的所有者权益",
    "归属于上市公司股东的净资产",
    "归属于上市公司股东的所有者权益（或股东权益）",
    "归属于母公司股东权益",
    "归属于母公司所有者权益",
    "归属于母公司所有者权益（或股东权益）",
    "归属于本行股东权益",
    "归属于本行普通股股东的净资产",
)


@dataclass(frozen=True)
class MetricRule:
    key: str
    terms: tuple[str, ...]
    excludes: tuple[str, ...] = ()


METRIC_RULES: tuple[MetricRule, ...] = (
    MetricRule("revenue", ("营业收入", "营业总收入"), ("其中营业收入",)),
    MetricRule("net_profit_attributable", ATTRIBUTABLE_TERMS),
    MetricRule(
        "net_profit",
        (
            "净利润（净亏损以“－”号填列）",
            "净利润（净亏损以“-”号填列）",
            "五、净利润（净亏损以“－”号填列）",
            "五、净利润（净亏损以“-”号填列）",
            "1.持续经营净利润（净亏损以“－”号填列）",
            "1.持续经营净利润（净亏损以“-”号填列）",
            "净利润",
        ),
        ATTRIBUTABLE_TERMS + ("扣除非经常性损益", "非经常性损益",),
    ),
    MetricRule("total_assets", ("总资产", "资产总额")),
    MetricRule(
        "total_liabilities",
        ("总负债", "负债总额", "负债合计"),
        ("流动负债合计", "非流动负债合计", "递延所得税负债"),
    ),
    MetricRule("equity_attributable", EQUITY_TERMS),
    MetricRule("operating_cash_flow", ("经营活动产生的现金流量净额",)),
    MetricRule("eps_basic", ("基本每股收益",)),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export PDF-based candidate lines and a seed manual-gold dataset for facts evaluation."
    )
    parser.add_argument(
        "--candidate-json",
        default=str(PROJECT_ROOT / "data" / "manual_truth" / "facts_gold_candidates_2026q1_26docs.json"),
    )
    parser.add_argument(
        "--candidate-csv",
        default=str(PROJECT_ROOT / "data" / "manual_truth" / "facts_gold_candidates_2026q1_26docs.csv"),
    )
    parser.add_argument(
        "--seed-dataset",
        default=str(PROJECT_ROOT / "tests" / "facts_eval_gold_seed_2026q1_26docs.json"),
    )
    parser.add_argument(
        "--report-period",
        default="2026Q1",
    )
    parser.add_argument(
        "--title-suffix",
        default="_2026_Q1报",
    )
    return parser.parse_args()


def extract_pdf_text(pdf_path: Path) -> list[str]:
    result = subprocess.run(
        ["pdftotext", "-layout", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.split("\f")


def normalize_line(line: str) -> str:
    return re.sub(r"\s+", "", line)


def extract_numeric_strings(text: str) -> list[str]:
    return re.findall(r"-?[0-9][0-9,]*(?:\.\d+)?", text)


def parse_number(text: str | None) -> float | None:
    if text is None:
        return None
    compact = text.replace(",", "").strip()
    if not compact:
        return None
    try:
        return float(compact)
    except ValueError:
        return None


def detect_page_unit(page: str) -> str | None:
    head = "\n".join(page.splitlines()[:40])
    match = re.search(r"单位[:：]\s*([^\n]{1,30})", head)
    if match:
        return match.group(1).strip()
    if "人民币百万元" in head:
        return "人民币百万元"
    if "单位：万元" in head:
        return "万元"
    if "单位：亿元" in head:
        return "亿元"
    if "单位：元" in head:
        return "元"
    return None


def unit_multiplier(unit: str | None) -> float | None:
    if not unit:
        return None
    compact = unit.replace(" ", "")
    if "百万元" in compact:
        return 1_000_000.0
    if "亿元" in compact:
        return 100_000_000.0
    if "万元" in compact:
        return 10_000.0
    if "千元" in compact:
        return 1_000.0
    if "元" in compact:
        return 1.0
    return None


def strip_eps_footnote(raw_values: list[str]) -> list[str]:
    if not raw_values:
        return raw_values
    first = raw_values[0]
    if first.isdigit() and int(first) <= 9 and len(raw_values) >= 2:
        return raw_values[1:]
    return raw_values


def strip_leading_footnote(raw_values: list[str]) -> list[str]:
    if not raw_values:
        return raw_values
    first = raw_values[0]
    if first.isdigit() and int(first) <= 9 and len(raw_values) >= 2:
        return raw_values[1:]
    return raw_values


def line_score(metric_key: str, line: str, page_number: int, term: str) -> float:
    normalized = normalize_line(line)
    score = 0.0
    number_count = len(extract_numeric_strings(line))
    if page_number <= 3:
        score += 2.0
    elif page_number <= 6:
        score += 0.8
    if any(token in line for token in ("主要会计数据", "主要财务指标")):
        score += 4.0
    if any(token in line for token in ("合并资产负债表", "合并利润表", "合并现金流量表")):
        score += 1.2
    if any(token in line for token in ("本报告期末", "报告期末", "2026年1-3月", "2026 年 1-3 月")):
        score += 1.0
    if "单位" in line or "人民币百万元" in line:
        score += 0.5
    term_pos = normalized.find(normalize_line(term))
    if term_pos == 0:
        score += 1.5
    elif 0 < term_pos <= 6:
        score += 0.8
    if metric_key == "net_profit" and any(token in line for token in ATTRIBUTABLE_TERMS):
        score -= 5.0
    if metric_key == "net_profit" and "持续经营净利润" in line:
        score -= 0.4
    if metric_key in {"revenue", "net_profit_attributable", "operating_cash_flow", "eps_basic"} and number_count >= 3:
        score += 0.6
    if metric_key in {"total_assets", "total_liabilities", "equity_attributable"} and number_count >= 2:
        score += 0.4
    if number_count <= 1:
        score -= 2.0
    return score


def propose_value(metric_key: str, line: str, term: str) -> str | None:
    compact = line.strip()
    start = compact.find(term)
    if start < 0:
        normalized_line = normalize_line(compact)
        normalized_term = normalize_line(term)
        pos = normalized_line.find(normalized_term)
        if pos < 0:
            return None
        # Fall back to using the whole line if the exact raw term location is unclear.
        tail = compact
    else:
        tail = compact[start + len(term) :]
    raw_values = extract_numeric_strings(tail)
    if metric_key == "eps_basic":
        raw_values = strip_eps_footnote(raw_values)
    elif metric_key == "operating_cash_flow":
        raw_values = strip_leading_footnote(raw_values)
    if not raw_values:
        return None
    return raw_values[0]


def build_candidates_for_metric(metric: MetricRule, pages: list[str]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for page_index, page in enumerate(pages, start=1):
        page_unit = detect_page_unit(page)
        multiplier = unit_multiplier(page_unit)
        base_lines = [line.rstrip() for line in page.splitlines() if line.strip()]
        lines: list[tuple[str, str]] = [(line, line) for line in base_lines]
        for idx in range(len(base_lines) - 1):
            merged = f"{base_lines[idx]} {base_lines[idx + 1]}".strip()
            lines.append((merged, base_lines[idx]))
        for line, anchor_line in lines:
            if any(exclude in line for exclude in metric.excludes):
                continue
            for term in metric.terms:
                if term not in line:
                    continue
                value = propose_value(metric.key, line, term)
                if value is None:
                    continue
                score = line_score(metric.key, line, page_index, term)
                candidates.append(
                    {
                        "page": page_index,
                        "term": term,
                        "line": line.strip(),
                        "anchor_line": anchor_line.strip(),
                        "value": value,
                        "unit": page_unit,
                        "numeric_value": parse_number(value),
                        "normalized_value_cny": None,
                        "score": round(score, 2),
                    }
                )
                break
        for item in candidates:
            if item["page"] != page_index:
                continue
            if item.get("numeric_value") is None or multiplier is None:
                continue
            if metric.key == "eps_basic":
                continue
            item["normalized_value_cny"] = round(item["numeric_value"] * multiplier, 4)
    candidates.sort(key=lambda item: (-item["score"], item["page"], item["line"]))
    return candidates


def build_seed_dataset(candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    facts_cases: list[dict[str, Any]] = []
    for row in candidate_rows:
        expected_metrics = {
            metric_key: {
                "value": metric_payload["value"],
                "expected_unit": metric_payload.get("unit"),
                "expected_numeric_value": metric_payload.get("numeric_value"),
                "expected_normalized_value_cny": metric_payload.get("normalized_value_cny"),
            }
            for metric_key, metric_payload in row["selected_metrics"].items()
            if metric_payload.get("value") is not None
        }
        facts_cases.append(
            {
                "document_title": row["document_title"],
                "expected_report_period": row["report_period"],
                "expected_metrics": expected_metrics,
            }
        )
    return {
        "parse_cases": [],
        "chunk_cases": [],
        "retrieval_cases": [],
        "facts_cases": facts_cases,
        "answer_cases": [],
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=[
                "document_title",
                "metric",
                "value",
                "unit",
                "normalized_value_cny",
                "page",
                "term",
                "score",
                "line",
            ],
        )
        writer.writeheader()
        for row in rows:
            for metric_key, metric_payload in row["selected_metrics"].items():
                writer.writerow(
                    {
                        "document_title": row["document_title"],
                        "metric": metric_key,
                        "value": metric_payload.get("value"),
                        "unit": metric_payload.get("unit"),
                        "normalized_value_cny": metric_payload.get("normalized_value_cny"),
                        "page": metric_payload.get("page"),
                        "term": metric_payload.get("term"),
                        "score": metric_payload.get("score"),
                        "line": metric_payload.get("line"),
                    }
                )


def main() -> None:
    args = parse_args()
    candidate_json_path = Path(args.candidate_json)
    candidate_csv_path = Path(args.candidate_csv)
    seed_dataset_path = Path(args.seed_dataset)
    candidate_json_path.parent.mkdir(parents=True, exist_ok=True)
    seed_dataset_path.parent.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        docs = db.scalars(select(Document).order_by(Document.title)).all()
        rows: list[dict[str, Any]] = []
        for document in docs:
            if args.title_suffix and not document.title.endswith(args.title_suffix):
                continue
            pdf_path = Path(document.source)
            if not pdf_path.exists():
                continue
            pages = extract_pdf_text(pdf_path)
            selected_metrics: dict[str, dict[str, Any]] = {}
            candidates_by_metric: dict[str, list[dict[str, Any]]] = {}
            for metric in METRIC_RULES:
                metric_candidates = build_candidates_for_metric(metric, pages)
                candidates_by_metric[metric.key] = metric_candidates[:5]
                selected_metrics[metric.key] = metric_candidates[0] if metric_candidates else {}
            rows.append(
                {
                    "document_title": document.title,
                    "pdf_path": str(pdf_path),
                    "report_period": args.report_period,
                    "selected_metrics": selected_metrics,
                    "candidates": candidates_by_metric,
                }
            )

        candidate_json_path.write_text(
            json.dumps(rows, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_csv(candidate_csv_path, rows)
        seed_dataset_path.write_text(
            json.dumps(build_seed_dataset(rows), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "candidate_json": str(candidate_json_path),
                    "candidate_csv": str(candidate_csv_path),
                    "seed_dataset": str(seed_dataset_path),
                    "documents": len(rows),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
