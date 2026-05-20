from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select

from app.core.database import SessionLocal, initialize_database
from app.models.query_log import QueryLog
from app.models.query_log_review import QueryLogReview


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="List recent query logs or attach manual review labels for replay."
    )
    parser.add_argument(
        "--list-recent",
        type=int,
        default=10,
        help="How many recent query logs to list when no review is being created.",
    )
    parser.add_argument("--query-log-id", type=int, help="Existing query log id to review.")
    parser.add_argument("--label", help="Review label, e.g. wrong_value or bad_refusal.")
    parser.add_argument(
        "--expected-answer-contains",
        action="append",
        default=[],
        help="Expected answer fragment. Repeat this flag for multiple fragments.",
    )
    parser.add_argument(
        "--expected-citation-title",
        help="Expected citation title for the reviewed failure.",
    )
    parser.add_argument("--note", help="Free-form review note.")
    parser.add_argument(
        "--status",
        default="open",
        choices=("open", "resolved", "ignored"),
        help="Review status when creating a review.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    initialize_database()
    db = SessionLocal()
    try:
        if args.query_log_id:
            create_review(db, args)
        else:
            list_recent(db, args.list_recent)
    finally:
        db.close()


def list_recent(db, limit: int) -> None:
    rows = db.execute(
        select(QueryLog).order_by(QueryLog.created_at.desc(), QueryLog.id.desc()).limit(limit)
    ).scalars()
    payload = []
    for row in rows:
        sources = row.sources if isinstance(row.sources, dict) else {}
        payload.append(
            {
                "id": row.id,
                "created_at": row.created_at.isoformat(),
                "query": row.query,
                "latency_ms": row.latency_ms,
                "request_tag": sources.get("request_tag"),
                "answer_mode": sources.get("answer_mode"),
                "guard_passed": sources.get("guard_passed"),
                "answer_preview": row.answer[:160],
            }
        )
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def create_review(db, args: argparse.Namespace) -> None:
    if not args.label:
        raise SystemExit("--label is required when --query-log-id is provided")

    query_log = db.get(QueryLog, args.query_log_id)
    if query_log is None:
        raise SystemExit(f"query log {args.query_log_id} not found")

    review = QueryLogReview(
        query_log_id=query_log.id,
        label=args.label,
        status=args.status,
        expected_answer_contains=args.expected_answer_contains,
        expected_citation_title=args.expected_citation_title,
        note=args.note,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    print(
        json.dumps(
            {
                "review_id": review.id,
                "query_log_id": review.query_log_id,
                "label": review.label,
                "status": review.status,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
