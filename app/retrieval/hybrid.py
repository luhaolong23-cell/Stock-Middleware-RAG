from __future__ import annotations

from dataclasses import dataclass, field

from app.models.chunk import Chunk


@dataclass
class ScoredChunk:
    chunk: Chunk
    score: float
    reasons: list[str] = field(default_factory=list)


class HybridRetriever:
    def __init__(self, rank_constant: int = 60) -> None:
        self.rank_constant = rank_constant

    def merge(
        self,
        keyword_hits: list[ScoredChunk],
        vector_hits: list[ScoredChunk],
        top_k: int = 10,
    ) -> list[ScoredChunk]:
        merged: dict[int, ScoredChunk] = {}

        for rank, hit in enumerate(keyword_hits, start=1):
            item = merged.setdefault(hit.chunk.id, ScoredChunk(chunk=hit.chunk, score=0.0))
            item.score += 1.0 / (self.rank_constant + rank)
            item.reasons.extend(hit.reasons)

        for rank, hit in enumerate(vector_hits, start=1):
            item = merged.setdefault(hit.chunk.id, ScoredChunk(chunk=hit.chunk, score=0.0))
            item.score += 1.0 / (self.rank_constant + rank)
            item.reasons.extend(hit.reasons)

        ordered = sorted(
            merged.values(),
            key=lambda item: (item.score, item.chunk.page_number or 0, item.chunk.chunk_index),
            reverse=True,
        )
        return ordered[:top_k]
