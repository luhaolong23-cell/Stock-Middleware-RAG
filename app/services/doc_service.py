from __future__ import annotations

import re

from sqlalchemy import func, or_
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.database import is_postgres_db
from app.ingestion.parser import ParsedDocument
from app.models.chunk import Chunk
from app.models.document import Document
from app.models.document_artifact import DocumentArtifact


class DocService:
    def __init__(self, db: Session) -> None:
        self.db = db

    def create_document(
        self,
        parsed: ParsedDocument,
        metadata: dict,
        chunk_records: list[dict],
        overwrite: bool = True,
    ) -> tuple[Document, int]:
        replaced_count = 0
        if overwrite:
            replaced_count = self._remove_existing_documents(parsed, metadata)

        document = Document(
            title=parsed.title,
            source=parsed.source,
            doc_type=parsed.doc_type,
            company=metadata.get("company"),
            ticker=metadata.get("ticker"),
            industry=metadata.get("industry"),
            published_at=metadata.get("published_at"),
            version=metadata.get("version", "v1"),
            raw_text=parsed.text,
        )
        use_postgres = is_postgres_db(self.db.bind)

        for record in chunk_records:
            tokenized_text = record.get("tokenized_text")
            document.chunks.append(
                Chunk(
                    chunk_index=record["chunk_index"],
                    chunk_type=record.get("chunk_type", "text"),
                    section_title=record.get("section_title"),
                    page_number=record.get("page_number"),
                    table_title=record.get("table_title"),
                    figure_title=record.get("figure_title"),
                    content=record["content"],
                    token_count=record["token_count"],
                    tokenized_text=tokenized_text,
                    search_vector=(
                        func.to_tsvector("simple", tokenized_text)
                        if use_postgres and tokenized_text
                        else tokenized_text
                    ),
                    embedding=record.get("embedding"),
                )
            )

        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)
        return document, replaced_count

    def list_documents(self) -> list[dict]:
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks), selectinload(Document.artifacts))
            .order_by(Document.id.desc())
        )
        documents = self.db.scalars(stmt).all()
        return [
            {
                "id": document.id,
                "title": document.title,
                "source": document.source,
                "doc_type": document.doc_type,
                "company": document.company,
                "ticker": document.ticker,
                "industry": document.industry,
                "published_at": document.published_at,
                "version": document.version,
                "chunk_count": len(document.chunks),
                "artifact_types": sorted({artifact.artifact_type for artifact in document.artifacts}),
            }
            for document in documents
        ]

    def get_document(self, document_id: int) -> Document | None:
        stmt = (
            select(Document)
            .options(selectinload(Document.chunks), selectinload(Document.artifacts))
            .where(Document.id == document_id)
        )
        return self.db.scalars(stmt).first()

    def _remove_existing_documents(self, parsed: ParsedDocument, metadata: dict) -> int:
        candidates: dict[int, Document] = {}
        exact_stmt = select(Document).where(
            or_(Document.source == parsed.source, Document.title == parsed.title)
        )
        for document in self.db.scalars(exact_stmt).all():
            candidates[document.id] = document

        ticker = metadata.get("ticker")
        report_identity = self._report_identity(parsed.title, parsed.source)
        if ticker and report_identity:
            ticker_stmt = select(Document).where(Document.ticker == ticker)
            for document in self.db.scalars(ticker_stmt).all():
                if self._report_identity(document.title, document.source) == report_identity:
                    candidates[document.id] = document

        for document in candidates.values():
            self.db.delete(document)
        if candidates:
            self.db.flush()
        return len(candidates)

    def _report_identity(self, title: str, source: str) -> str | None:
        haystack = f"{title} {source}"
        year_match = re.search(r"(20\d{2})", haystack)
        report_markers = (
            ("年报", "annual"),
            ("年度报告", "annual"),
            ("半年报", "semiannual"),
            ("半年度报告", "semiannual"),
            ("q1", "q1"),
            ("一季报", "q1"),
            ("第一季度", "q1"),
            ("q3", "q3"),
            ("三季报", "q3"),
            ("第三季度", "q3"),
            ("季报", "quarterly"),
            ("季度报告", "quarterly"),
        )
        report_type = next(
            (value for marker, value in report_markers if marker.lower() in haystack.lower()),
            None,
        )
        if not year_match and not report_type:
            return None
        year = year_match.group(1) if year_match else "unknown"
        report = report_type or "unknown"
        return f"{year}:{report}"
