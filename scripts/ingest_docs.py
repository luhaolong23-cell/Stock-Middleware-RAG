from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import Base, SessionLocal, engine
from app.ingestion.pipeline import IngestionPipeline


def main(paths: list[str]) -> None:
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    pipeline = IngestionPipeline(db)
    try:
        for file_path in paths:
            result = pipeline.run(file_path, overwrite=True)
            print(
                f"ingested {result['title']} -> {result['chunk_count']} chunks "
                f"(replaced {result['replaced_count']}, strategy={result['strategy']})"
            )
    finally:
        db.close()


if __name__ == "__main__":
    args = sys.argv[1:]
    if len(args) < 1:
        raise SystemExit("usage: python scripts/ingest_docs.py <file> [file...]")
    main(args)
