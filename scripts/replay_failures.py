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
from app.services.chat_service import ChatService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Replay manually labeled query failures against the current answer stack."
    )
    parser.add_argument("--review-id", type=int, action="append", default=[])
    parser.add_argument("--status", default="open", help="Replay reviews with this status.")
    parser.add_argument("--limit", type=int, default=20)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    initialize_database()
    db = SessionLocal()
    try:
        service = ChatService(db)
        reviews = load_reviews(db, args.review_id, args.status, args.limit)
        results = [replay_review(service, review) for review in reviews]
        passed = sum(1 for result in results if result["passed"])
        print(
            json.dumps(
                {
                    "total": len(results),
                    "passed": passed,
                    "pass_rate": round(passed / len(results), 4) if results else 0.0,
                    "results": results,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    finally:
        db.close()


def load_reviews(
    db,
    review_ids: list[int],
    status: str,
    limit: int,
) -> list[tuple[QueryLogReview, QueryLog]]:
    stmt = select(QueryLogReview, QueryLog).join(QueryLog, QueryLog.id == QueryLogReview.query_log_id)
    if review_ids:
        stmt = stmt.where(QueryLogReview.id.in_(review_ids))
    else:
        stmt = stmt.where(QueryLogReview.status == status).limit(limit)
    stmt = stmt.order_by(QueryLogReview.created_at.desc(), QueryLogReview.id.desc())
    return list(db.execute(stmt).all())


def replay_review(service: ChatService, row: tuple[QueryLogReview, QueryLog]) -> dict:
    review, query_log = row
    sources = query_log.sources if isinstance(query_log.sources, dict) else {}
    top_k = int(sources.get("top_k", 5))
    original_citations = sources.get("citations", []) if isinstance(sources, dict) else []
    response = service.answer(
        query=query_log.query,
        top_k=top_k,
        log_query=False,
        request_tag="replay",
    )

    answer = response["answer"]
    citations = response["citations"]
    checks = []

    for needle in review.expected_answer_contains or []:
        checks.append(
            {
                "check": f"answer_contains:{needle}",
                "passed": needle in answer,
            }
        )

    if review.expected_citation_title:
        checks.append(
            {
                "check": f"citation_title:{review.expected_citation_title}",
                "passed": any(
                    citation.get("title") == review.expected_citation_title for citation in citations
                ),
            }
        )

    if review.label == "should_refuse":
        checks.append(
            {
                "check": "should_refuse",
                "passed": "没有足够证据" in answer,
            }
        )
    elif review.label == "bad_refusal":
        checks.append(
            {
                "check": "bad_refusal",
                "passed": "没有足够证据" not in answer,
            }
        )

    passed = all(item["passed"] for item in checks) if checks else answer != query_log.answer
    return {
        "review_id": review.id,
        "query_log_id": query_log.id,
        "label": review.label,
        "status": review.status,
        "query": query_log.query,
        "passed": passed,
        "checks": checks,
        "original_answer_preview": query_log.answer[:200],
        "replayed_answer_preview": answer[:200],
        "original_citation_titles": [item.get("title") for item in original_citations[:5]],
        "replayed_citation_titles": [item.get("title") for item in citations[:5]],
    }


if __name__ == "__main__":
    main()
