from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.core.database import Base, SearchVectorColumn, VectorColumn


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index", name="uq_chunks_document_chunk_index"),
        Index("ix_chunks_document_id", "document_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_type: Mapped[str] = mapped_column(String(16), nullable=False, default="text")
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    table_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    figure_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    token_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    tokenized_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    search_vector: Mapped[str | None] = mapped_column(SearchVectorColumn(), nullable=True)
    embedding: Mapped[list[float] | None] = mapped_column(
        VectorColumn(settings.embedding_dimensions), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    document: Mapped["Document"] = relationship("Document", back_populates="chunks")
