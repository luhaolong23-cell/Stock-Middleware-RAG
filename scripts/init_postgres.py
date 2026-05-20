from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import initialize_database, is_postgres_db
from app.models.chunk import Chunk  # noqa: F401
from app.models.document import Document  # noqa: F401


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Initialize PostgreSQL schema, pgvector extension, and indexes."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", "").strip(),
        help="PostgreSQL DSN. Defaults to DATABASE_URL.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.database_url:
        raise SystemExit("DATABASE_URL is required")

    engine = create_engine(args.database_url, future=True, pool_pre_ping=True)
    if not is_postgres_db(engine):
        raise SystemExit("target database must be PostgreSQL")

    initialize_database(engine)
    print("initialized PostgreSQL schema and pgvector indexes")


if __name__ == "__main__":
    main()
