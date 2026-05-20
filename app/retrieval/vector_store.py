from __future__ import annotations

import logging

from app.models.chunk import Chunk
from app.retrieval.embedder import SimpleEmbedder, cosine_similarity
from app.retrieval.hybrid import ScoredChunk

logger = logging.getLogger(__name__)


class VectorRetriever:
    def __init__(self) -> None:
        self.embedder = SimpleEmbedder(allow_fallback=False)

    def search(self, query: str, chunks: list[Chunk], top_k: int = 10) -> list[ScoredChunk]:
        try:
            query_embedding = self.embedder.embed(query)
        except Exception as exc:
            logger.warning("skipping vector retrieval because query embedding failed: %s", exc)
            return []
        results: list[ScoredChunk] = []

        for chunk in chunks:
            if not chunk.embedding:
                continue
            score = cosine_similarity(query_embedding, chunk.embedding)
            if score <= 0:
                continue
            results.append(
                ScoredChunk(chunk=chunk, score=score, reasons=["vector_similarity"])
            )

        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]
