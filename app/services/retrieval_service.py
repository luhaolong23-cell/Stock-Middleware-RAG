from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import logging
import re

from sqlalchemy import func, or_, select, text
from sqlalchemy.exc import DataError
from sqlalchemy.orm import Session, joinedload

from app.core.database import is_postgres_db, vector_literal
from app.models.chunk import Chunk
from app.models.document import Document
from app.retrieval.bm25 import (
    KeywordRetriever,
    build_lexical_text,
    lexical_tokenize,
)
from app.retrieval.hybrid import HybridRetriever, ScoredChunk
from app.retrieval.reranker import SimpleReranker
from app.retrieval.vector_store import VectorRetriever

logger = logging.getLogger(__name__)


@dataclass
class QueryMetadata:
    ticker: str | None = None
    company: str | None = None
    year: int | None = None
    title_terms: list[str] = field(default_factory=list)
    report_terms: list[str] = field(default_factory=list)

    @property
    def has_filters(self) -> bool:
        return bool(
            self.ticker or self.company or self.year or self.title_terms or self.report_terms
        )


@dataclass(frozen=True)
class MetadataCacheState:
    document_count: int
    latest_updated_at: datetime | None


@dataclass(frozen=True)
class MetadataCachePayload:
    state: MetadataCacheState
    companies: tuple[str, ...]
    title_terms: tuple[str, ...]


class RetrievalService:
    REPORT_TERM_MAP = {
        "年报": ["年报", "年度报告"],
        "年度报告": ["年报", "年度报告"],
        "半年报": ["半年报", "半年度报告"],
        "半年度报告": ["半年报", "半年度报告"],
        "季报": ["季报", "季度报告"],
        "季度报告": ["季报", "季度报告"],
        "一季报": ["q1", "一季报", "第一季度"],
        "q1": ["q1", "一季报", "第一季度"],
        "三季报": ["q3", "三季报", "第三季度"],
        "q3": ["q3", "三季报", "第三季度"],
        "公告": ["公告"],
        "研报": ["研报"],
    }
    _metadata_cache: dict[str, MetadataCachePayload] = {}

    def __init__(self, db: Session) -> None:
        self.db = db
        self.use_postgres_search = is_postgres_db(db.bind)
        self.keyword = KeywordRetriever()
        self.vector = VectorRetriever()
        self.hybrid = HybridRetriever()
        self.reranker = SimpleReranker()

    def retrieve(self, query: str, top_k: int = 5) -> list[ScoredChunk]:
        metadata = self._infer_query_metadata(query)
        candidate_k = top_k * 8
        if self.use_postgres_search:
            keyword_hits = self._keyword_search_db(query, metadata, top_k=candidate_k)
            vector_hits = self._vector_search_db(query, metadata, top_k=candidate_k)
        else:
            chunks = self._load_chunks(metadata)
            keyword_hits = self.keyword.search(query, chunks, top_k=candidate_k)
            vector_hits = self.vector.search(query, chunks, top_k=candidate_k)
        merged_hits = self.hybrid.merge(keyword_hits, vector_hits, top_k=candidate_k)
        return self.reranker.rank(query, merged_hits, top_k=top_k)

    def _load_chunks(self, metadata: QueryMetadata) -> list[Chunk]:
        filtered = self._load_filtered_chunks(metadata)
        if filtered:
            return filtered

        stmt = select(Chunk).options(joinedload(Chunk.document))
        return self.db.scalars(stmt).all()

    def _load_filtered_chunks(self, metadata: QueryMetadata) -> list[Chunk]:
        if not metadata.has_filters:
            return []

        stmt = (
            select(Chunk)
            .join(Chunk.document)
            .options(joinedload(Chunk.document))
        )
        stmt = self._apply_metadata_filters(stmt, metadata)
        return self.db.scalars(stmt).all()

    def _keyword_search_db(
        self, query: str, metadata: QueryMetadata, top_k: int
    ) -> list[ScoredChunk]:
        query_tokens = " ".join(lexical_tokenize(query))
        if not query_tokens:
            return []

        ts_query = func.plainto_tsquery("simple", query_tokens)
        score_expr = func.ts_rank(Chunk.search_vector, ts_query)
        stmt = (
            select(Chunk, score_expr.label("score"))
            .join(Chunk.document)
            .options(joinedload(Chunk.document))
            .where(Chunk.search_vector.is_not(None))
            .where(Chunk.search_vector.op("@@")(ts_query))
        )
        stmt = self._apply_metadata_filters(stmt, metadata)
        stmt = stmt.order_by(score_expr.desc(), Chunk.page_number, Chunk.chunk_index).limit(top_k)

        rows = self.db.execute(stmt).all()
        hits: list[ScoredChunk] = []
        for chunk, score in rows:
            lexical_text = build_lexical_text(
                content=chunk.content,
                document_title=chunk.document.title if chunk.document else None,
                company=chunk.document.company if chunk.document else None,
                ticker=chunk.document.ticker if chunk.document else None,
                section_title=chunk.section_title,
                table_title=chunk.table_title,
                figure_title=chunk.figure_title,
            )
            final_score = float(score or 0.0)
            if query in lexical_text:
                final_score += 1.0
            hits.append(ScoredChunk(chunk=chunk, score=final_score, reasons=["bm25_db"]))
        return hits

    def _vector_search_db(
        self, query: str, metadata: QueryMetadata, top_k: int
    ) -> list[ScoredChunk]:
        try:
            query_embedding = self.vector.embedder.embed(query)
        except Exception as exc:
            logger.warning(
                "skipping vector search because query embedding failed: %s",
                exc,
            )
            return []
        if not query_embedding:
            return []

        sql_conditions = ["c.embedding IS NOT NULL"]
        params: dict[str, object] = {
            "query_embedding": vector_literal(query_embedding),
            "limit": top_k,
        }
        self._append_sql_metadata_filters(sql_conditions, params, metadata)
        where_clause = " AND ".join(sql_conditions)
        sql = text(
            f"""
            SELECT
                c.id AS chunk_id,
                1 - (c.embedding <=> CAST(:query_embedding AS vector)) AS score
            FROM chunks c
            JOIN documents d ON d.id = c.document_id
            WHERE {where_clause}
            ORDER BY c.embedding <=> CAST(:query_embedding AS vector), c.page_number, c.chunk_index
            LIMIT :limit
            """
        )
        try:
            rows = self.db.execute(sql, params).all()
        except DataError as exc:
            # If the current query embedder no longer matches the stored corpus
            # dimensionality, keep the request alive by falling back to lexical search.
            if "different vector dimensions" in str(exc).lower():
                self.db.rollback()
                logger.warning(
                    "skipping vector search because query embedding dimensions do not match stored embeddings"
                )
                return []
            raise
        if not rows:
            return []

        ordered_ids = [int(row.chunk_id) for row in rows]
        score_by_id = {int(row.chunk_id): float(row.score or 0.0) for row in rows}
        chunk_stmt = (
            select(Chunk)
            .options(joinedload(Chunk.document))
            .where(Chunk.id.in_(ordered_ids))
        )
        chunk_map = {chunk.id: chunk for chunk in self.db.scalars(chunk_stmt).all()}
        hits: list[ScoredChunk] = []
        for chunk_id in ordered_ids:
            chunk = chunk_map.get(chunk_id)
            if chunk is None:
                continue
            hits.append(
                ScoredChunk(
                    chunk=chunk,
                    score=score_by_id[chunk_id],
                    reasons=["vector_similarity_db"],
                )
            )
        return hits

    def _infer_query_metadata(self, query: str) -> QueryMetadata:
        metadata = QueryMetadata()
        ticker_match = re.search(r"\b(\d{6})\b", query)
        if ticker_match:
            metadata.ticker = ticker_match.group(1)

        year_match = re.search(r"\b(20\d{2})\b", query)
        if year_match:
            metadata.year = int(year_match.group(1))

        matched_report_terms: list[str] = []
        lowered = query.lower()
        for trigger, report_terms in self.REPORT_TERM_MAP.items():
            if trigger.lower() in lowered:
                matched_report_terms.extend(report_terms)
        metadata.report_terms = list(dict.fromkeys(matched_report_terms))

        metadata_payload = self._metadata_payload()
        company_candidates = [
            company for company in metadata_payload.companies if company and company in query
        ]
        if company_candidates:
            metadata.company = max(company_candidates, key=len)

        metadata.title_terms = [
            term for term in metadata_payload.title_terms if term in query
        ]

        return metadata

    def _title_candidate_terms(self, title: str) -> list[str]:
        terms: list[str] = []
        for segment in re.split(r"[_\-\s]+", title):
            compact = segment.strip()
            if len(compact) < 2:
                continue
            if re.fullmatch(r"\d{4,}", compact):
                continue
            if compact in {"年报", "半年报", "季报", "公告", "研报"}:
                continue
            if re.search(r"[\u4e00-\u9fff]", compact):
                terms.append(compact)
        return terms

    def _metadata_payload(self) -> MetadataCachePayload:
        bind = self.db.bind
        bind_key = str(getattr(bind, "url", "default"))
        state = self._metadata_cache_state()
        cached = self._metadata_cache.get(bind_key)
        if cached and cached.state == state:
            return cached

        companies = tuple(
            sorted(
                {
                    company.strip()
                    for company in self.db.scalars(
                        select(Document.company).where(Document.company.is_not(None))
                    ).all()
                    if company and company.strip()
                },
                key=len,
                reverse=True,
            )
        )
        title_terms = tuple(
            dict.fromkeys(
                term
                for title in self.db.scalars(select(Document.title)).all()
                for term in self._title_candidate_terms(title or "")
            )
        )
        payload = MetadataCachePayload(
            state=state,
            companies=companies,
            title_terms=title_terms,
        )
        self._metadata_cache[bind_key] = payload
        return payload

    def _metadata_cache_state(self) -> MetadataCacheState:
        document_count, latest_updated_at = self.db.execute(
            select(func.count(Document.id), func.max(Document.updated_at))
        ).one()
        return MetadataCacheState(
            document_count=int(document_count or 0),
            latest_updated_at=latest_updated_at,
        )

    def _apply_metadata_filters(self, stmt, metadata: QueryMetadata):
        if metadata.ticker:
            stmt = stmt.where(Document.ticker == metadata.ticker)
        if metadata.company:
            stmt = stmt.where(Document.company == metadata.company)
        if metadata.title_terms:
            stmt = stmt.where(
                or_(*[Document.title.contains(term) for term in metadata.title_terms])
            )
        if metadata.year:
            year_text = str(metadata.year)
            stmt = stmt.where(
                or_(
                    Document.title.contains(year_text),
                    Document.source.contains(year_text),
                )
            )
        if metadata.report_terms:
            title_filters = [
                Document.title.contains(term) for term in metadata.report_terms
            ] + [
                Document.source.contains(term) for term in metadata.report_terms
            ]
            stmt = stmt.where(or_(*title_filters))
        return stmt

    def _append_sql_metadata_filters(
        self,
        sql_conditions: list[str],
        params: dict[str, object],
        metadata: QueryMetadata,
    ) -> None:
        if metadata.ticker:
            sql_conditions.append("d.ticker = :ticker")
            params["ticker"] = metadata.ticker
        if metadata.company:
            sql_conditions.append("d.company = :company")
            params["company"] = metadata.company
        if metadata.title_terms:
            placeholders = []
            for idx, term in enumerate(metadata.title_terms):
                key = f"title_term_{idx}"
                placeholders.append(f"d.title ILIKE :{key}")
                params[key] = f"%{term}%"
            if placeholders:
                sql_conditions.append("(" + " OR ".join(placeholders) + ")")
        if metadata.year:
            params["year_text"] = f"%{metadata.year}%"
            sql_conditions.append("(d.title ILIKE :year_text OR d.source ILIKE :year_text)")
        if metadata.report_terms:
            placeholders = []
            for idx, term in enumerate(metadata.report_terms):
                title_key = f"report_title_{idx}"
                source_key = f"report_source_{idx}"
                placeholders.append(f"d.title ILIKE :{title_key}")
                placeholders.append(f"d.source ILIKE :{source_key}")
                params[title_key] = f"%{term}%"
                params[source_key] = f"%{term}%"
            if placeholders:
                sql_conditions.append("(" + " OR ".join(placeholders) + ")")
