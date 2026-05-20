from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Integer, JSON, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class QueryLog(Base):
    __tablename__ = "query_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    query: Mapped[str] = mapped_column(Text, nullable=False)
    rewritten_query: Mapped[str] = mapped_column(Text, nullable=False)
    answer: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
