from __future__ import annotations

import sys
from math import ceil
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.core.database import is_postgres_db
from app.core.database import SessionLocal
from app.models.chunk import Chunk
from app.retrieval.bm25 import lexical_tokenize
from app.retrieval.embedder import SimpleEmbedder, build_embedding_text


def main() -> None:
    db = SessionLocal()
    embedder = SimpleEmbedder(allow_fallback=False)
    batch_size = 100
    try:
        chunks = db.scalars(select(Chunk).options(joinedload(Chunk.document))).all()
        use_postgres = is_postgres_db(db.bind)
        total = len(chunks)
        total_batches = max(ceil(total / batch_size), 1)
        print(
            f"rebuilding embeddings for {total} chunks in {total_batches} batches "
            f"(batch_size={batch_size})",
            flush=True,
        )

        if use_postgres:
            from sqlalchemy import func

        for batch_index, start in enumerate(range(0, total, batch_size), start=1):
            batch = chunks[start : start + batch_size]
            embedding_inputs = [_build_embedding_source(chunk) for chunk in batch]
            embeddings = embedder.embed_texts(embedding_inputs)
            for chunk, embedding, embedding_source in zip(batch, embeddings, embedding_inputs):
                tokenized_text = " ".join(lexical_tokenize(embedding_source))
                chunk.embedding = embedding
                chunk.tokenized_text = tokenized_text
                if use_postgres:
                    chunk.search_vector = (
                        func.to_tsvector("simple", tokenized_text) if tokenized_text else None
                    )
                else:
                    chunk.search_vector = tokenized_text
            db.commit()
            completed = min(start + len(batch), total)
            progress = completed / max(total, 1) * 100
            print(
                f"[{batch_index}/{total_batches}] rebuilt {completed}/{total} chunks "
                f"({progress:.1f}%)",
                flush=True,
            )

        print(f"rebuilt embeddings for {len(chunks)} chunks")
    finally:
        db.close()


def _build_embedding_source(chunk: Chunk) -> str:
    return build_embedding_text(
        content=chunk.content,
        document_title=chunk.document.title if chunk.document else None,
        company=chunk.document.company if chunk.document else None,
        ticker=chunk.document.ticker if chunk.document else None,
        section_title=chunk.section_title,
        table_title=chunk.table_title,
        figure_title=chunk.figure_title,
    )


if __name__ == "__main__":
    main()
