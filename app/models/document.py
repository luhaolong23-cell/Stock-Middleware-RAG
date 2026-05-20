from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        Index("ix_documents_company", "company"),
        Index("ix_documents_ticker", "ticker"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    source: Mapped[str] = mapped_column(String(1024), nullable=False, unique=True)
    doc_type: Mapped[str] = mapped_column(String(32), nullable=False)
    company: Mapped[str | None] = mapped_column(String(128), nullable=True)
    ticker: Mapped[str | None] = mapped_column(String(16), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(64), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    version: Mapped[str] = mapped_column(String(32), default="v1", nullable=False)
    raw_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    chunks: Mapped[list["Chunk"]] = relationship(
        "Chunk", back_populates="document", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list["DocumentArtifact"]] = relationship(
        "DocumentArtifact",
        back_populates="document",
        cascade="all, delete-orphan",
    )
