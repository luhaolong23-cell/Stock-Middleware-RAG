from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.ingestion.chunker_unstructured import FinancialReportChunkerV2
from app.ingestion.parser import DocumentParser, ParsedDocument
from app.models.document import Document
from app.services.artifact_service import ArtifactService
from app.services.chat_service import ChatService
from app.services.retrieval_service import RetrievalService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate parser, chunker, retrieval, and answer layers independently."
    )
    parser.add_argument("eval_file", help="JSON file describing evaluation cases.")
    parser.add_argument(
        "--layer",
        choices=("parse", "chunk", "retrieval", "facts", "answer", "all"),
        default="all",
        help="Which layer to evaluate.",
    )
    return parser.parse_args()


def main(eval_file: str, layer: str) -> None:
    dataset = json.loads(Path(eval_file).read_text(encoding="utf-8"))
    summary: dict[str, Any] = {}

    if layer in {"parse", "all"}:
        summary["parse"] = eval_parse_cases(dataset.get("parse_cases", []))

    if layer in {"chunk", "all"}:
        summary["chunk"] = eval_chunk_cases(dataset.get("chunk_cases", []))

    if layer in {"retrieval", "all"}:
        summary["retrieval"] = eval_retrieval_cases(dataset.get("retrieval_cases", []))

    if layer in {"facts", "all"}:
        summary["facts"] = eval_facts_cases(dataset.get("facts_cases", []))

    if layer in {"answer", "all"}:
        summary["answer"] = eval_answer_cases(dataset.get("answer_cases", []))

    print(json.dumps(summary, ensure_ascii=False, indent=2))


def eval_parse_cases(cases: list[dict]) -> dict:
    parser = DocumentParser()
    results: list[dict] = []
    passed = 0
    for case in cases:
        parsed = parser.parse(str(resolve_path(case["file_path"])))
        element_counts = Counter(element.element_type for element in parsed.elements)
        checks = []

        expected_text = case.get("expected_text_contains", [])
        for needle in expected_text:
            checks.append(
                {
                    "check": f"text_contains:{needle}",
                    "passed": needle in parsed.text,
                }
            )

        for element_type, minimum in case.get("min_element_counts", {}).items():
            checks.append(
                {
                    "check": f"min_element_counts:{element_type}",
                    "passed": element_counts.get(element_type, 0) >= minimum,
                    "actual": element_counts.get(element_type, 0),
                    "expected_min": minimum,
                }
            )

        ok = all(item["passed"] for item in checks) if checks else True
        passed += int(ok)
        results.append(
            {
                "name": case.get("name", Path(case["file_path"]).name),
                "passed": ok,
                "title": parsed.title,
                "text_length": len(parsed.text),
                "element_counts": dict(element_counts),
                "checks": checks,
            }
        )

    return {
        "total": len(cases),
        "passed": passed,
        "pass_rate": round(passed / len(cases), 4) if cases else 0.0,
        "results": results,
    }


def eval_chunk_cases(cases: list[dict]) -> dict:
    parser = DocumentParser()
    chunker = FinancialReportChunkerV2()
    results: list[dict] = []
    passed = 0

    for case in cases:
        parsed = parser.parse(str(resolve_path(case["file_path"])))
        chunks = chunker.split_elements(parsed.elements)
        chunk_counts = Counter(chunk.chunk_type for chunk in chunks)
        lengths = [len(chunk.content) for chunk in chunks]
        checks = []

        if "min_chunks" in case:
            checks.append(
                {
                    "check": "min_chunks",
                    "passed": len(chunks) >= case["min_chunks"],
                    "actual": len(chunks),
                    "expected_min": case["min_chunks"],
                }
            )
        if "max_chunk_length" in case:
            checks.append(
                {
                    "check": "max_chunk_length",
                    "passed": (max(lengths) if lengths else 0) <= case["max_chunk_length"],
                    "actual": max(lengths) if lengths else 0,
                    "expected_max": case["max_chunk_length"],
                }
            )
        for element_type, minimum in case.get("min_chunk_counts", {}).items():
            checks.append(
                {
                    "check": f"min_chunk_counts:{element_type}",
                    "passed": chunk_counts.get(element_type, 0) >= minimum,
                    "actual": chunk_counts.get(element_type, 0),
                    "expected_min": minimum,
                }
            )
        if "required_keyword" in case:
            keyword = case["required_keyword"]
            checks.append(
                {
                    "check": f"required_keyword:{keyword}",
                    "passed": any(keyword in chunk.content for chunk in chunks),
                }
            )

        ok = all(item["passed"] for item in checks) if checks else True
        passed += int(ok)
        results.append(
            {
                "name": case.get("name", Path(case["file_path"]).name),
                "passed": ok,
                "strategy": "v2",
                "chunk_count": len(chunks),
                "chunk_type_counts": dict(chunk_counts),
                "avg_chunk_length": round(sum(lengths) / len(lengths), 2) if lengths else 0,
                "max_chunk_length": max(lengths) if lengths else 0,
                "checks": checks,
            }
        )

    return {
        "total": len(cases),
        "passed": passed,
        "pass_rate": round(passed / len(cases), 4) if cases else 0.0,
        "results": results,
    }


def eval_retrieval_cases(cases: list[dict]) -> dict:
    db = SessionLocal()
    service = RetrievalService(db)
    results: list[dict] = []
    top1_hits = 0
    top3_hits = 0
    try:
        for case in cases:
            top_k = max(case.get("top_k", 5), 3)
            hits = service.retrieve(case["query"], top_k=top_k)
            ranks = match_ranks(case, hits)
            top1_hits += int(1 in ranks)
            top3_hits += int(any(rank <= 3 for rank in ranks))
            results.append(
                {
                    "query": case["query"],
                    "match_ranks": ranks,
                    "top_hit": serialize_hit(hits[0]) if hits else None,
                }
            )
    finally:
        db.close()

    total = len(cases)
    return {
        "total": total,
        "top1_hit_rate": round(top1_hits / total, 4) if total else 0.0,
        "top3_hit_rate": round(top3_hits / total, 4) if total else 0.0,
        "results": results,
    }


def eval_answer_cases(cases: list[dict]) -> dict:
    db = SessionLocal()
    service = ChatService(db)
    results: list[dict] = []
    passed = 0
    try:
        for case in cases:
            response = service.answer(
                case["query"],
                top_k=case.get("top_k", 5),
                log_query=False,
                request_tag="eval",
            )
            answer = response["answer"]
            citations = response["citations"]
            checks = []

            for needle in case.get("expected_answer_contains", []):
                checks.append(
                    {
                        "check": f"answer_contains:{needle}",
                        "passed": needle in answer,
                    }
                )

            expected_title = case.get("expected_citation_title")
            if expected_title:
                checks.append(
                    {
                        "check": f"citation_title:{expected_title}",
                        "passed": any(
                            citation.get("title") == expected_title for citation in citations
                        ),
                    }
                )

            forbid_refusal = case.get("forbid_refusal", False)
            if forbid_refusal:
                checks.append(
                    {
                        "check": "forbid_refusal",
                        "passed": "没有足够证据" not in answer,
                    }
                )

            ok = all(item["passed"] for item in checks) if checks else True
            passed += int(ok)
            results.append(
                {
                    "query": case["query"],
                    "passed": ok,
                    "answer_preview": answer[:240],
                    "citation_count": len(citations),
                    "checks": checks,
                }
            )
    finally:
        db.close()

    return {
        "total": len(cases),
        "passed": passed,
        "pass_rate": round(passed / len(cases), 4) if cases else 0.0,
        "results": results,
    }


def eval_facts_cases(cases: list[dict]) -> dict:
    db = SessionLocal()
    service = ArtifactService(db)
    results: list[dict] = []
    passed = 0
    try:
        for case in cases:
            document = db.scalars(
                select(Document).where(Document.title == case["document_title"])
            ).first()
            if document is None:
                results.append(
                    {
                        "document_title": case["document_title"],
                        "passed": False,
                        "error": "document_not_found",
                        "checks": [],
                    }
                )
                continue

            artifacts = service.generate_and_persist(document)
            facts_payload = artifacts["extract_facts"]
            analysis_payload = artifacts["analyze_fundamentals"]
            metrics = facts_payload["metrics"]
            checks = []

            expected_period = case.get("expected_report_period")
            if expected_period:
                checks.append(
                    {
                        "check": f"report_period:{expected_period}",
                        "passed": facts_payload["report_period"] == expected_period,
                        "actual": facts_payload["report_period"],
                    }
                )

            for metric_key, expected in case.get("expected_metrics", {}).items():
                fact = metrics.get(metric_key)
                checks.append(
                    {
                        "check": f"metric_present:{metric_key}",
                        "passed": fact is not None,
                    }
                )
                if fact is None:
                    continue
                if "value" in expected:
                    checks.append(
                        {
                            "check": f"value:{metric_key}",
                            "passed": fact.get("value") == expected["value"],
                            "actual": fact.get("value"),
                        }
                    )
                if "min_confidence" in expected:
                    checks.append(
                        {
                            "check": f"min_confidence:{metric_key}",
                            "passed": float(fact.get("confidence", 0.0)) >= expected["min_confidence"],
                            "actual": fact.get("confidence"),
                        }
                    )
                if "source_page" in expected:
                    checks.append(
                        {
                            "check": f"source_page:{metric_key}",
                            "passed": fact.get("source_page") == expected["source_page"],
                            "actual": fact.get("source_page"),
                        }
                    )
                if "quality_flag" in expected:
                    checks.append(
                        {
                            "check": f"quality_flag:{metric_key}",
                            "passed": fact.get("quality_flag") == expected["quality_flag"],
                            "actual": fact.get("quality_flag"),
                        }
                    )
                if "fact_origin" in expected:
                    checks.append(
                        {
                            "check": f"fact_origin:{metric_key}",
                            "passed": fact.get("fact_origin") == expected["fact_origin"],
                            "actual": fact.get("fact_origin"),
                        }
                    )

            expected_derived_metrics = case.get("expected_derived_metrics")
            if expected_derived_metrics is not None:
                actual_derived_metrics = facts_payload["data_quality"].get("derived_metrics", [])
                checks.append(
                    {
                        "check": "derived_metrics",
                        "passed": actual_derived_metrics == expected_derived_metrics,
                        "actual": actual_derived_metrics,
                    }
                )

            for list_key, expected_items in case.get("expected_usable_for_calc_contains", {}).items():
                actual_items = analysis_payload.get("usable_for_calc", {}).get(list_key, [])
                checks.append(
                    {
                        "check": f"usable_for_calc_contains:{list_key}",
                        "passed": all(item in actual_items for item in expected_items),
                        "actual": actual_items,
                    }
                )

            ok = all(item["passed"] for item in checks) if checks else True
            passed += int(ok)
            results.append(
                {
                    "document_title": case["document_title"],
                    "passed": ok,
                    "checks": checks,
                }
            )
    finally:
        db.close()

    return {
        "total": len(cases),
        "passed": passed,
        "pass_rate": round(passed / len(cases), 4) if cases else 0.0,
        "results": results,
    }
def match_ranks(item: dict, hits: list) -> list[int]:
    matched: list[int] = []
    expected_title = item.get("expected_title")
    expected_page = item.get("expected_page")
    expected_section = item.get("expected_section")
    expected_chunk_type = item.get("expected_chunk_type")
    expected_keywords = item.get("expected_keywords", [])

    for rank, hit in enumerate(hits, start=1):
        chunk = hit.chunk
        if expected_title and chunk.document and chunk.document.title != expected_title:
            continue
        if expected_page is not None and chunk.page_number != expected_page:
            continue
        if expected_section and chunk.section_title != expected_section:
            continue
        if expected_chunk_type and chunk.chunk_type != expected_chunk_type:
            continue
        if expected_keywords and not all(keyword in chunk.content for keyword in expected_keywords):
            continue
        matched.append(rank)
    return matched


def serialize_hit(hit) -> dict:
    chunk = hit.chunk
    return {
        "title": chunk.document.title if chunk.document else None,
        "page_number": chunk.page_number,
        "chunk_type": chunk.chunk_type,
        "section_title": chunk.section_title,
        "table_title": chunk.table_title,
        "score": round(hit.score, 6),
        "snippet": chunk.content[:180],
    }


def resolve_path(path_text: str) -> Path:
    path = Path(path_text)
    if path.is_absolute():
        return path
    return PROJECT_ROOT / path


if __name__ == "__main__":
    args = parse_args()
    main(args.eval_file, layer=args.layer)
