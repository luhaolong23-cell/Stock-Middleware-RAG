from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.models.document import Document
from app.services.artifact_service import ArtifactService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export a structured-facts evaluation dataset from current document artifacts."
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "tests" / "facts_eval_2026q1_26docs.json"),
        help="Path to the evaluation dataset JSON file to write.",
    )
    parser.add_argument(
        "--report-period",
        default="2026Q1",
        help="Only include documents whose extracted report_period matches this value.",
    )
    parser.add_argument(
        "--title-suffix",
        default="_2026_Q1报",
        help="Only include documents whose title ends with this suffix.",
    )
    return parser.parse_args()


def confidence_threshold(value: Any) -> float | None:
    if value is None:
        return None
    confidence = float(value)
    if confidence <= 0:
        return None
    for threshold in (0.9, 0.8, 0.7, 0.6, 0.5):
        if confidence >= threshold:
            return threshold
    return math.floor(confidence * 100) / 100


def build_expected_metric(fact: dict[str, Any]) -> dict[str, Any]:
    expected: dict[str, Any] = {"value": fact.get("value")}
    threshold = confidence_threshold(fact.get("confidence"))
    if threshold is not None:
        expected["min_confidence"] = threshold
    for key in ("source_page", "quality_flag", "fact_origin"):
        value = fact.get(key)
        if value is not None and value != "":
            expected[key] = value
    return expected


def main() -> None:
    args = parse_args()
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        artifact_service = ArtifactService(db)
        docs = db.scalars(select(Document).order_by(Document.title)).all()
        facts_cases: list[dict[str, Any]] = []

        for document in docs:
            if args.title_suffix and not document.title.endswith(args.title_suffix):
                continue

            artifacts = artifact_service.generate_and_persist(document)
            facts_payload = artifacts["extract_facts"]
            analysis_payload = artifacts["analyze_fundamentals"]

            if args.report_period and facts_payload.get("report_period") != args.report_period:
                continue

            metrics = facts_payload.get("metrics", {})
            expected_metrics = {
                metric_key: build_expected_metric(fact)
                for metric_key, fact in metrics.items()
                if fact is not None
            }
            usable_for_calc = analysis_payload.get("usable_for_calc", {})
            facts_cases.append(
                {
                    "document_title": document.title,
                    "expected_report_period": facts_payload.get("report_period"),
                    "expected_metrics": expected_metrics,
                    "expected_derived_metrics": facts_payload.get("data_quality", {}).get(
                        "derived_metrics",
                        [],
                    ),
                    "expected_usable_for_calc_contains": {
                        "raw_metrics": usable_for_calc.get("raw_metrics", []),
                        "derived_metrics": usable_for_calc.get("derived_metrics", []),
                        "excluded_metrics": usable_for_calc.get("excluded_metrics", []),
                    },
                }
            )

        payload = {
            "parse_cases": [],
            "chunk_cases": [],
            "retrieval_cases": [],
            "facts_cases": facts_cases,
            "answer_cases": [],
        }
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(
            json.dumps(
                {
                    "output": str(output_path),
                    "facts_cases": len(facts_cases),
                    "report_period": args.report_period,
                    "title_suffix": args.title_suffix,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


if __name__ == "__main__":
    main()
