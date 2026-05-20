from __future__ import annotations

import argparse
import json
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


EPS_METRIC_KEYS = {"eps_basic"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare current extract_facts artifacts against a manual gold dataset."
    )
    parser.add_argument(
        "--dataset",
        default=str(PROJECT_ROOT / "tests" / "facts_eval_gold_manual_2026q1_26docs.json"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    dataset = json.loads(Path(args.dataset).read_text(encoding="utf-8"))
    cases = dataset.get("facts_cases", [])

    db = SessionLocal()
    artifact_service = ArtifactService(db)
    try:
        total_fields = 0
        matched_fields = 0
        document_exact_matches = 0
        results: list[dict[str, Any]] = []
        field_stats: dict[str, dict[str, int]] = {}

        for case in cases:
            document = db.scalars(
                select(Document).where(Document.title == case["document_title"])
            ).first()
            if document is None:
                results.append(
                    {
                        "document_title": case["document_title"],
                        "error": "document_not_found",
                    }
                )
                continue

            artifacts = artifact_service.generate_and_persist(document)
            actual_metrics = artifacts["extract_facts"].get("metrics", {})
            per_doc_ok = True
            field_results: list[dict[str, Any]] = []

            for metric_key, expected in case.get("expected_metrics", {}).items():
                total_fields += 1
                stat = field_stats.setdefault(metric_key, {"total": 0, "matched": 0})
                stat["total"] += 1

                actual_metric = actual_metrics.get(metric_key)
                actual_value = actual_metric.get("value") if actual_metric else None
                actual_numeric = actual_metric.get("numeric_value") if actual_metric else None
                actual_normalized = actual_metric.get("normalized_value_cny") if actual_metric else None
                expected_value = expected.get("value")
                expected_numeric = expected.get("expected_numeric_value")
                expected_normalized = expected.get("expected_normalized_value_cny")

                if metric_key in EPS_METRIC_KEYS and expected_numeric is not None:
                    matched = actual_numeric is not None and abs(float(actual_numeric) - float(expected_numeric)) < 1e-9
                elif expected_normalized is not None:
                    matched = actual_normalized is not None and abs(float(actual_normalized) - float(expected_normalized)) < 1e-6
                else:
                    matched = actual_value == expected_value
                matched_fields += int(matched)
                stat["matched"] += int(matched)
                per_doc_ok &= matched

                field_results.append(
                    {
                        "metric": metric_key,
                        "expected_value": expected_value,
                        "expected_numeric_value": expected_numeric,
                        "expected_normalized_value_cny": expected_normalized,
                        "actual_value": actual_value,
                        "actual_numeric_value": actual_numeric,
                        "actual_normalized_value_cny": actual_normalized,
                        "matched": matched,
                    }
                )

            document_exact_matches += int(per_doc_ok)
            results.append(
                {
                    "document_title": case["document_title"],
                    "matched": per_doc_ok,
                    "field_results": field_results,
                }
            )

        field_accuracy = {
            key: {
                **value,
                "accuracy": round(value["matched"] / value["total"], 4) if value["total"] else 0.0,
            }
            for key, value in sorted(field_stats.items())
        }
        summary = {
            "documents": len(cases),
            "document_exact_matches": document_exact_matches,
            "document_exact_match_rate": round(document_exact_matches / len(cases), 4)
            if cases
            else 0.0,
            "total_fields": total_fields,
            "matched_fields": matched_fields,
            "field_accuracy": round(matched_fields / total_fields, 4) if total_fields else 0.0,
            "field_breakdown": field_accuracy,
            "mismatched_documents": [
                item for item in results if item.get("matched") is False
            ],
        }
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
