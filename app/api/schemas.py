from __future__ import annotations

from typing import Any
from datetime import datetime
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    query: str = Field(..., min_length=1)
    top_k: int = Field(default=5, ge=1, le=20)


class CitationItem(BaseModel):
    document_id: int
    title: str
    source: str
    doc_type: str
    chunk_type: str
    section_title: str | None = None
    page_number: int | None = None
    table_title: str | None = None
    figure_title: str | None = None
    published_at: datetime | None = None
    snippet: str
    score: float


class ChatResponse(BaseModel):
    query: str
    rewritten_query: str
    answer: str
    citations: list[CitationItem]


class IngestRequest(BaseModel):
    file_path: str = Field(..., min_length=1)
    overwrite: bool = True


class IngestResponse(BaseModel):
    document_id: int
    title: str
    chunk_count: int
    replaced_count: int = 0
    strategy: str = "v2"
    artifacts: dict[str, Any] = Field(default_factory=dict)


class DocumentArtifactResponse(BaseModel):
    artifact_type: str
    version: str
    status: str
    payload: dict[str, Any]
    created_at: datetime
    updated_at: datetime


class DocumentResponse(BaseModel):
    id: int
    title: str
    source: str
    doc_type: str
    company: str | None = None
    ticker: str | None = None
    industry: str | None = None
    published_at: datetime | None = None
    version: str
    chunk_count: int
    artifact_types: list[str] = Field(default_factory=list)
