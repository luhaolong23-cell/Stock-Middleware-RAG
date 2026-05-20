from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, delete, func, select
from sqlalchemy.orm import Session, joinedload, sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import Base, ensure_postgres_extensions, ensure_postgres_indexes, is_postgres_db
from app.models.chunk import Chunk
from app.models.document import Document
from app.retrieval.bm25 import lexical_tokenize
from app.retrieval.embedder import build_embedding_text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Migrate existing SQLite data into PostgreSQL with pgvector/tsvector fields."
    )
    parser.add_argument(
        "--source-url",
        default=f"sqlite:///{(PROJECT_ROOT / 'data' / 'stock_rag.db').as_posix()}",
        help="Source SQLAlchemy database URL. Defaults to the local SQLite database.",
    )
    parser.add_argument(
        "--dest-url",
        default=os.getenv("DATABASE_URL", "").strip(),
        help="Destination PostgreSQL URL. Defaults to DATABASE_URL.",
    )
    parser.add_argument(
        "--truncate",
        action="store_true",
        help="Delete existing destination rows before migrating.",
    )
    return parser.parse_args()


def build_tokenized_text(document: Document, chunk: Chunk) -> str:
    lexical_text = build_embedding_text(
        content=chunk.content,
        document_title=document.title,
        company=document.company,
        ticker=document.ticker,
        section_title=chunk.section_title,
        table_title=chunk.table_title,
        figure_title=chunk.figure_title,
    )
    return " ".join(lexical_tokenize(lexical_text))


def copy_document(dest_db: Session, source_doc: Document) -> None:
    existing = dest_db.scalar(select(Document).where(Document.source == source_doc.source))
    if existing is not None:
        dest_db.delete(existing)
        dest_db.flush()

    new_doc = Document(
        title=source_doc.title,
        source=source_doc.source,
        doc_type=source_doc.doc_type,
        company=source_doc.company,
        ticker=source_doc.ticker,
        industry=source_doc.industry,
        published_at=source_doc.published_at,
        version=source_doc.version,
        raw_text=source_doc.raw_text,
    )

    for source_chunk in sorted(source_doc.chunks, key=lambda item: item.chunk_index):
        tokenized_text = source_chunk.tokenized_text or build_tokenized_text(source_doc, source_chunk)
        new_doc.chunks.append(
            Chunk(
                chunk_index=source_chunk.chunk_index,
                chunk_type=source_chunk.chunk_type,
                section_title=source_chunk.section_title,
                page_number=source_chunk.page_number,
                table_title=source_chunk.table_title,
                figure_title=source_chunk.figure_title,
                content=source_chunk.content,
                token_count=source_chunk.token_count,
                tokenized_text=tokenized_text,
                search_vector=(
                    func.to_tsvector("simple", tokenized_text)
                    if tokenized_text
                    else None
                ),
                embedding=source_chunk.embedding,
            )
        )

    dest_db.add(new_doc)


def main() -> None:
    args = parse_args()
    if not args.dest_url:
        raise SystemExit("destination PostgreSQL URL is required")

    source_engine = create_engine(args.source_url, future=True, pool_pre_ping=True)
    dest_engine = create_engine(args.dest_url, future=True, pool_pre_ping=True)

    if not is_postgres_db(dest_engine):
        raise SystemExit("destination must be PostgreSQL")

    ensure_postgres_extensions(dest_engine)
    Base.metadata.create_all(bind=dest_engine)
    ensure_postgres_indexes(dest_engine)

    SourceSession = sessionmaker(
        bind=source_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )
    DestSession = sessionmaker(
        bind=dest_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )

    source_db = SourceSession()
    dest_db = DestSession()
    try:
        if args.truncate:
            dest_db.execute(delete(Chunk))
            dest_db.execute(delete(Document))
            dest_db.commit()

        documents = source_db.scalars(
            select(Document)
            .options(joinedload(Document.chunks))
            .order_by(Document.id)
        ).unique().all()

        for document in documents:
            copy_document(dest_db, document)

        dest_db.commit()
        total_chunks = sum(len(document.chunks) for document in documents)
        print(f"migrated {len(documents)} documents and {total_chunks} chunks")
    finally:
        source_db.close()
        dest_db.close()


if __name__ == "__main__":
    main()
