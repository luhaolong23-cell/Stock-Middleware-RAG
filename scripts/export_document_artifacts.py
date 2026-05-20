from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.models.document import Document
from app.models.document_artifact import DocumentArtifact


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export one document's structured artifacts to JSON."
    )
    parser.add_argument(
        "target",
        help="Document id or 6-digit ticker. A ticker exports the newest matching document.",
    )
    parser.add_argument(
        "--output",
        help="Exact output file path. Defaults to data/exports/document_<id>_artifacts.json",
    )
    parser.add_argument(
        "--stdout",
        action="store_true",
        help="Print JSON to stdout instead of writing a file.",
    )
    parser.add_argument(
        "--by",
        choices=("auto", "document-id", "ticker"),
        default="auto",
        help="How to interpret target. Default: auto.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db = SessionLocal()
    try:
        document = resolve_document(db, args.target, args.by)

        rows = db.scalars(
            select(DocumentArtifact)
            .where(DocumentArtifact.document_id == document.id)
            .order_by(DocumentArtifact.artifact_type)
        ).all()
        if not rows:
            raise SystemExit(f"document {document.id} has no artifacts")

        payload = {
            "resolved_by": resolve_mode(args.target, args.by),
            "document": serialize_document(document),
            "artifact_count": len(rows),
            "artifacts": [serialize_artifact(row) for row in rows],
        }

        if args.stdout:
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return

        output_path = resolve_output_path(document.id, args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(output_path)
    finally:
        db.close()


def resolve_document(db, target: str, by: str) -> Document:
    mode = resolve_mode(target, by)
    if mode == "document-id":
        try:
            document_id = int(target)
        except ValueError as exc:
            raise SystemExit(f"invalid document id: {target}") from exc
        document = db.get(Document, document_id)
        if document is None:
            raise SystemExit(f"document {document_id} not found")
        return document

    stmt = (
        select(Document)
        .where(Document.ticker == target)
        .order_by(Document.published_at.desc().nullslast(), Document.id.desc())
    )
    documents = db.scalars(stmt).all()
    if not documents:
        raise SystemExit(f"no documents found for ticker {target}")
    return documents[0]


def resolve_mode(target: str, by: str) -> str:
    if by != "auto":
        return by
    if target.isdigit() and len(target) == 6:
        return "ticker"
    return "document-id"


def resolve_output_path(document_id: int, output: str | None) -> Path:
    if output:
        return Path(output)
    return PROJECT_ROOT / "data" / "exports" / f"document_{document_id}_artifacts.json"


def serialize_document(document: Document) -> dict[str, Any]:
    return {
        "id": document.id,
        "title": document.title,
        "source": document.source,
        "doc_type": document.doc_type,
        "company": document.company,
        "ticker": document.ticker,
        "industry": document.industry,
        "published_at": isoformat_or_none(document.published_at),
        "version": document.version,
        "created_at": isoformat_or_none(document.created_at),
        "updated_at": isoformat_or_none(document.updated_at),
    }


def serialize_artifact(row: DocumentArtifact) -> dict[str, Any]:
    return {
        "artifact_type": row.artifact_type,
        "version": row.version,
        "status": row.status,
        "created_at": isoformat_or_none(row.created_at),
        "updated_at": isoformat_or_none(row.updated_at),
        "payload": row.payload,
    }


def isoformat_or_none(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


if __name__ == "__main__":
    main()
