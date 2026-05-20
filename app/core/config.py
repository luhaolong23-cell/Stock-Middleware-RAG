from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
ENV_FILE = BASE_DIR / ".env"


def _load_env_file(path: Path) -> None:
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key or key in os.environ:
            continue
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


_load_env_file(ENV_FILE)


@dataclass(frozen=True)
class Settings:
    app_name: str
    app_env: str
    database_url: str
    log_level: str
    default_top_k: int
    embedding_dimensions: int
    embedding_base_url: str
    embedding_api_key: str
    embedding_model: str
    embedding_timeout_seconds: int
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_timeout_seconds: int
    llm_max_tokens: int
    llm_temperature: float
    min_answer_score: float


settings = Settings(
    app_name=os.getenv("APP_NAME", "Stock RAG Research Assistant"),
    app_env=os.getenv("APP_ENV", "dev"),
    database_url=os.getenv(
        "DATABASE_URL", f"sqlite:///{(DATA_DIR / 'stock_rag.db').as_posix()}"
    ),
    log_level=os.getenv("LOG_LEVEL", "INFO"),
    default_top_k=int(os.getenv("DEFAULT_TOP_K", "5")),
    embedding_dimensions=int(os.getenv("EMBEDDING_DIMENSIONS", "1536")),
    embedding_base_url=os.getenv("EMBEDDING_BASE_URL", "").strip(),
    embedding_api_key=os.getenv("EMBEDDING_API_KEY", "").strip(),
    embedding_model=os.getenv("EMBEDDING_MODEL", "").strip(),
    embedding_timeout_seconds=int(os.getenv("EMBEDDING_TIMEOUT_SECONDS", "60")),
    llm_base_url=os.getenv("LLM_BASE_URL", "").strip(),
    llm_api_key=os.getenv("LLM_API_KEY", "").strip(),
    llm_model=os.getenv("LLM_MODEL", "").strip(),
    llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
    llm_max_tokens=int(os.getenv("LLM_MAX_TOKENS", "800")),
    llm_temperature=float(os.getenv("LLM_TEMPERATURE", "0.1")),
    min_answer_score=float(os.getenv("MIN_ANSWER_SCORE", "0.015")),
)
