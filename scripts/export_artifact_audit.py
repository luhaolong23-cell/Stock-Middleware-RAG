from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime
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
        description="Generate an artifact audit snapshot for all ingested documents."
    )
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "data" / "audits"),
        help="Directory to write audit snapshot files into.",
    )
    parser.add_argument(
        "--prefix",
        default="artifact_audit",
        help="Filename prefix for the generated json/csv files.",
    )
    parser.add_argument(
        "--timestamp",
        default=datetime.now().strftime("%Y%m%d-%H%M%S"),
        help="Timestamp suffix for output filenames.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    db = SessionLocal()
    try:
        docs = db.scalars(select(Document).order_by(Document.id)).all()
        artifact_service = ArtifactService(db)
        rows: list[dict[str, Any]] = []
        industry_counter: Counter[str] = Counter()
        missing_counter: Counter[str] = Counter()
        low_conf_counter: Counter[str] = Counter()
        derived_counter: Counter[str] = Counter()
        errors: list[dict[str, Any]] = []

        for document in docs:
            try:
                artifacts = artifact_service.generate_and_persist(document)
                extract = artifacts["extract_facts"]
                analysis = artifacts["analyze_fundamentals"]
                basic_info = extract.get("basic_info", {})
                missing_metrics = extract.get("data_quality", {}).get("missing_metrics", [])
                derived_metrics = extract.get("data_quality", {}).get("derived_metrics", [])
                low_confidence_metrics = analysis.get("data_quality", {}).get(
                    "low_confidence_metrics", []
                )
                usable_for_calc = analysis.get("usable_for_calc", {})
                industry = basic_info.get("industry")

                if industry:
                    industry_counter[industry] += 1
                missing_counter.update(missing_metrics)
                low_conf_counter.update(low_confidence_metrics)
                derived_counter.update(derived_metrics)

                rows.append(
                    {
                        "document_id": document.id,
                        "title": document.title,
                        "company": document.company,
                        "ticker": document.ticker,
                        "industry": industry,
                        "report_period": extract.get("report_period"),
                        "report_type": extract.get("report_type"),
                        "fact_count": extract.get("data_quality", {}).get("fact_count", 0),
                        "available_metric_count": analysis.get("data_quality", {}).get(
                            "available_metric_count", 0
                        ),
                        "missing_metrics": missing_metrics,
                        "low_confidence_metrics": low_confidence_metrics,
                        "derived_metrics": derived_metrics,
                        "usable_raw_metrics": usable_for_calc.get("raw_metrics", []),
                        "usable_derived_metrics": usable_for_calc.get("derived_metrics", []),
                        "usable_excluded_metrics": usable_for_calc.get("excluded_metrics", []),
                        "summary": analysis.get("summary", []),
                    }
                )
            except Exception as exc:  # pragma: no cover - audit snapshot should continue
                errors.append(
                    {
                        "document_id": document.id,
                        "title": document.title,
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )

        summary = {
            "generated_at": datetime.now().isoformat(),
            "total_documents": len(docs),
            "generated_ok": len(rows),
            "generated_failed": len(errors),
            "with_industry": sum(1 for row in rows if row.get("industry")),
            "without_industry": sum(1 for row in rows if not row.get("industry")),
            "documents_with_missing_metrics": sum(1 for row in rows if row["missing_metrics"]),
            "documents_with_low_confidence_metrics": sum(
                1 for row in rows if row["low_confidence_metrics"]
            ),
            "documents_with_derived_metrics": sum(1 for row in rows if row["derived_metrics"]),
            "top_industries": industry_counter.most_common(20),
            "top_missing_metrics": missing_counter.most_common(),
            "top_low_confidence_metrics": low_conf_counter.most_common(),
            "top_derived_metrics": derived_counter.most_common(),
        }

        payload = {
            "summary": summary,
            "rows": rows,
            "errors": errors,
        }

        stem = f"{args.prefix}_{args.timestamp}"
        json_path = output_dir / f"{stem}.json"
        csv_path = output_dir / f"{stem}.csv"
        summary_path = output_dir / f"{stem}.summary.json"

        json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        summary_path.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        write_csv(csv_path, rows)

        print(
            json.dumps(
                {
                    "json": str(json_path),
                    "csv": str(csv_path),
                    "summary": str(summary_path),
                    "generated_ok": len(rows),
                    "generated_failed": len(errors),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames = [
        "document_id",
        "title",
        "company",
        "ticker",
        "industry",
        "report_period",
        "report_type",
        "fact_count",
        "available_metric_count",
        "missing_metrics",
        "low_confidence_metrics",
        "derived_metrics",
        "usable_raw_metrics",
        "usable_derived_metrics",
        "usable_excluded_metrics",
        "summary",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    key: stringify_list(row.get(key))
                    if isinstance(row.get(key), list)
                    else row.get(key)
                    for key in fieldnames
                }
            )


def stringify_list(value: Any) -> str:
    if not isinstance(value, list):
        return "" if value is None else str(value)
    return " | ".join(str(item) for item in value)


if __name__ == "__main__":
    main()
