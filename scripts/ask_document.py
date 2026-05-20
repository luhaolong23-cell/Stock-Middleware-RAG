from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import SessionLocal
from app.services.chat_service import ChatService


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ask a question against the local stock-RAG database without starting the API server."
    )
    parser.add_argument("query", help="Natural-language question to ask.")
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="How many citations to return. Default: 5.",
    )
    parser.add_argument(
        "--stdout-json",
        action="store_true",
        help="Print the full JSON response. Default output is a readable text summary.",
    )
    parser.add_argument(
        "--no-log",
        action="store_true",
        help="Do not persist a query log row.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    db = SessionLocal()
    try:
        service = ChatService(db)
        response = service.answer(
            query=args.query,
            top_k=args.top_k,
            log_query=not args.no_log,
            request_tag="script",
        )
    finally:
        db.close()

    if args.stdout_json:
        print(json.dumps(response, ensure_ascii=False, indent=2, default=str))
        return

    print(f"query: {response['query']}")
    print(f"rewritten_query: {response['rewritten_query']}")
    print("answer:")
    print(response["answer"])
    print("citations:")
    for index, item in enumerate(response["citations"], start=1):
        page = item.get("page_number")
        section = item.get("section_title") or "-"
        title = item.get("title") or "-"
        score = item.get("score")
        print(f"- [{index}] {title} page={page} score={score} section={section}")


if __name__ == "__main__":
    main()
