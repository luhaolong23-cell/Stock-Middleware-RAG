from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QueryLogReview(Base):
    __tablename__ = "query_log_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query_log_id: Mapped[int] = mapped_column(ForeignKey("query_logs.id"), nullable=False)
    label: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    expected_answer_contains: Mapped[list[str]] = mapped_column(
        JSON, nullable=False, default=list
    )
    expected_citation_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )
