from __future__ import annotations

from collections.abc import Generator
import json
from typing import Any

from sqlalchemy import Text, create_engine, text
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy.types import TypeDecorator, UserDefinedType

from app.core.config import settings


class Base(DeclarativeBase):
    pass


def _serialize_vector(value: list[float]) -> str:
    return "[" + ",".join(format(float(item), ".10g") for item in value) + "]"


def parse_vector(value: Any) -> list[float] | None:
    if value is None:
        return None
    if isinstance(value, list):
        return [float(item) for item in value]
    if isinstance(value, tuple):
        return [float(item) for item in value]
    if isinstance(value, str):
        compact = value.strip()
        if not compact:
            return None
        if compact.startswith("[") and compact.endswith("]"):
            payload = compact[1:-1].strip()
            if not payload:
                return []
            return [float(item.strip()) for item in payload.split(",") if item.strip()]
        try:
            decoded = json.loads(compact)
        except json.JSONDecodeError:
            return None
        if isinstance(decoded, list):
            return [float(item) for item in decoded]
    return None


def vector_literal(value: list[float]) -> str:
    return _serialize_vector(value)


class _PGVector(UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **_kw) -> str:
        return f"vector({self.dimensions})"


class VectorColumn(TypeDecorator):
    impl = Text
    cache_ok = True

    def __init__(self, dimensions: int) -> None:
        super().__init__()
        self.dimensions = dimensions

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(_PGVector(self.dimensions))
        return dialect.type_descriptor(Text())

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        vector = parse_vector(value)
        if vector is None:
            return None
        if dialect.name == "postgresql":
            return _serialize_vector(vector)
        return json.dumps(vector)

    def process_result_value(self, value, _dialect):
        return parse_vector(value)


class SearchVectorColumn(TypeDecorator):
    impl = Text
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(TSVECTOR())
        return dialect.type_descriptor(Text())


connect_args = (
    {"check_same_thread": False}
    if settings.database_url.startswith("sqlite")
    else {}
)
engine = create_engine(
    settings.database_url,
    future=True,
    connect_args=connect_args,
    pool_pre_ping=True,
)
SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def is_postgres_db(bind=None) -> bool:
    target = bind or engine
    return bool(target is not None and target.dialect.name == "postgresql")


def ensure_postgres_extensions(bind=None) -> None:
    target = bind or engine
    if not is_postgres_db(target):
        return
    with target.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))


def ensure_postgres_indexes(bind=None) -> None:
    target = bind or engine
    if not is_postgres_db(target):
        return
    with target.begin() as conn:
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_search_vector
                ON chunks USING GIN (search_vector)
                """
            )
        )
        conn.execute(
            text(
                """
                CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
                ON chunks USING hnsw (embedding vector_cosine_ops)
                """
            )
        )


def initialize_database(bind=None) -> None:
    target = bind or engine
    ensure_postgres_extensions(target)
    Base.metadata.create_all(bind=target)
    ensure_postgres_indexes(target)


def get_db() -> Generator:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
