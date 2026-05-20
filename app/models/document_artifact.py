from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class DocumentArtifact(Base):
    __tablename__ = "document_artifacts"
    __table_args__ = (
        UniqueConstraint(
            "document_id",
            "artifact_type",
            "version",
            name="uq_document_artifacts_document_type_version",
        ),
        Index("ix_document_artifacts_document_id", "document_id"),
        Index("ix_document_artifacts_artifact_type", "artifact_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"), nullable=False)
    artifact_type: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False, default="v1")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ready")
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    document: Mapped["Document"] = relationship("Document", back_populates="artifacts")
