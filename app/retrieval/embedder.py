from __future__ import annotations

import hashlib
import json
import logging
import math
import re
from urllib import error, request

from app.core.config import settings

logger = logging.getLogger(__name__)


def simple_tokenize(text: str) -> list[str]:
    word_tokens = re.findall(r"[A-Za-z0-9]+", text.lower())
    cjk_tokens = [char for char in text if "\u4e00" <= char <= "\u9fff"]
    return word_tokens + cjk_tokens


def build_embedding_text(
    content: str,
    document_title: str | None = None,
    company: str | None = None,
    ticker: str | None = None,
    section_title: str | None = None,
    table_title: str | None = None,
    figure_title: str | None = None,
) -> str:
    parts = [
        document_title or "",
        company or "",
        ticker or "",
        section_title or "",
        table_title or "",
        figure_title or "",
        content,
    ]
    return "\n".join(part for part in parts if part)


class HashEmbedder:
    def __init__(self, dimensions: int = 64) -> None:
        self.dimensions = dimensions

    def embed(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        vector = [0.0] * self.dimensions
        tokens = simple_tokenize(text)
        if not tokens:
            return vector

        for token in tokens:
            hashed = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16)
            index = hashed % self.dimensions
            vector[index] += 1.0

        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        return [value / norm for value in vector]


class OpenAICompatibleEmbedder:
    def __init__(
        self,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: int = 60,
        max_batch_size: int = 10,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.timeout_seconds = timeout_seconds
        self.max_batch_size = max_batch_size

    def embed(self, text: str) -> list[float]:
        return self.embed_texts([text])[0]

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []

        embeddings: list[list[float]] = []
        for start in range(0, len(texts), self.max_batch_size):
            batch = texts[start : start + self.max_batch_size]
            payload = {
                "model": self.model,
                "input": batch,
            }
            body = json.dumps(payload).encode("utf-8")
            headers = {"Content-Type": "application/json"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            req = request.Request(
                f"{self.base_url}/embeddings",
                data=body,
                headers=headers,
                method="POST",
            )
            try:
                with request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
            except error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="ignore")
                raise RuntimeError(f"embedding HTTP {exc.code}: {detail}") from exc

            items = data.get("data") or []
            if len(items) != len(batch):
                raise RuntimeError("embedding response size mismatch")

            ordered = sorted(items, key=lambda item: item.get("index", 0))
            batch_embeddings = [item.get("embedding") for item in ordered]
            if not all(isinstance(item, list) for item in batch_embeddings):
                raise RuntimeError("embedding response missing vectors")
            embeddings.extend(batch_embeddings)
        return embeddings


class SimpleEmbedder:
    def __init__(self, dimensions: int | None = None, allow_fallback: bool = True) -> None:
        if dimensions is None:
            dimensions = settings.embedding_dimensions
        self.primary_backend = None
        self.fallback_backend = None
        self.dimensions = dimensions
        self.allow_fallback = allow_fallback

        if settings.embedding_base_url and settings.embedding_model:
            logger.info(
                "using remote embedding endpoint %s with model %s",
                settings.embedding_base_url,
                settings.embedding_model,
            )
            self.primary_backend = OpenAICompatibleEmbedder(
                base_url=settings.embedding_base_url,
                api_key=settings.embedding_api_key,
                model=settings.embedding_model,
                timeout_seconds=settings.embedding_timeout_seconds,
                max_batch_size=10,
            )
            if allow_fallback:
                self.fallback_backend = HashEmbedder(dimensions=dimensions)
            return

        backend = HashEmbedder(dimensions=dimensions)
        self.primary_backend = backend
        self.dimensions = getattr(backend, "dimensions", dimensions)

    def _call_backend(self, method_name: str, *args):
        if self.primary_backend is None:
            raise RuntimeError("embedding backend is not initialized")
        try:
            return getattr(self.primary_backend, method_name)(*args)
        except Exception as exc:
            if self.fallback_backend is None or not self.allow_fallback:
                raise
            logger.exception("primary embedding backend failed: %s", exc)
            logger.warning("falling back to hash embedding backend")
            return getattr(self.fallback_backend, method_name)(*args)

    def embed(self, text: str) -> list[float]:
        return self._call_backend("embed", text)

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        return self._call_backend("embed_texts", texts)


def cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right:
        return 0.0
    return sum(a * b for a, b in zip(left, right))
