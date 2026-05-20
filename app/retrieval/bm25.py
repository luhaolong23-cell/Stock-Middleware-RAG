from __future__ import annotations

from collections import Counter
import math
import re

from app.models.chunk import Chunk
from app.retrieval.hybrid import ScoredChunk


def build_lexical_text(
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


class KeywordRetriever:
    def __init__(self, k1: float = 1.5, b: float = 0.75) -> None:
        self.k1 = k1
        self.b = b

    def search(self, query: str, chunks: list[Chunk], top_k: int = 10) -> list[ScoredChunk]:
        query_tokens = lexical_tokenize(query)
        if not query_tokens:
            return []

        documents = [self._document_text(chunk) for chunk in chunks]
        tokenized_docs = [lexical_tokenize(text) for text in documents]
        non_empty_lengths = [len(tokens) for tokens in tokenized_docs if tokens]
        avgdl = sum(non_empty_lengths) / max(len(non_empty_lengths), 1)
        doc_freqs = self._build_doc_frequencies(tokenized_docs)

        results: list[ScoredChunk] = []
        for chunk, tokens, text in zip(chunks, tokenized_docs, documents):
            if not tokens:
                continue

            score = self._bm25_score(
                query_tokens=query_tokens,
                doc_tokens=tokens,
                doc_freqs=doc_freqs,
                total_docs=len(tokenized_docs),
                avgdl=avgdl,
            )
            if score <= 0:
                continue

            if query in text:
                score += 1.0
            results.append(
                ScoredChunk(chunk=chunk, score=score, reasons=["bm25"])
            )

        return sorted(results, key=lambda item: item.score, reverse=True)[:top_k]

    def _document_text(self, chunk: Chunk) -> str:
        return build_lexical_text(
            content=chunk.content,
            document_title=chunk.document.title if chunk.document else None,
            company=chunk.document.company if chunk.document else None,
            ticker=chunk.document.ticker if chunk.document else None,
            section_title=chunk.section_title,
            table_title=chunk.table_title,
            figure_title=chunk.figure_title,
        )

    def _build_doc_frequencies(self, tokenized_docs: list[list[str]]) -> Counter[str]:
        frequencies: Counter[str] = Counter()
        for tokens in tokenized_docs:
            frequencies.update(set(tokens))
        return frequencies

    def _bm25_score(
        self,
        query_tokens: list[str],
        doc_tokens: list[str],
        doc_freqs: Counter[str],
        total_docs: int,
        avgdl: float,
    ) -> float:
        term_counts = Counter(doc_tokens)
        doc_len = len(doc_tokens)
        score = 0.0
        unique_query_tokens = list(dict.fromkeys(query_tokens))
        for token in unique_query_tokens:
            freq = term_counts.get(token, 0)
            if freq == 0:
                continue
            df = doc_freqs.get(token, 0)
            idf = math.log(1 + (total_docs - df + 0.5) / (df + 0.5))
            numerator = freq * (self.k1 + 1)
            denominator = freq + self.k1 * (
                1 - self.b + self.b * doc_len / max(avgdl, 1e-9)
            )
            score += idf * numerator / denominator
        return score


_LATIN_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._/-]*")
_CJK_SEQ_RE = re.compile(r"[\u4e00-\u9fff]+")
_STOP_TOKENS = {
    "公司",
    "什么",
    "情况",
    "是否",
    "以及",
    "其中",
    "有关",
    "进行",
    "根据",
    "关于",
    "主要",
    "本期",
    "期末",
    "期初",
}


def lexical_tokenize(text: str) -> list[str]:
    normalized = re.sub(r"\s+", " ", text).lower()
    tokens: list[str] = []

    tokens.extend(match.group(0) for match in _LATIN_TOKEN_RE.finditer(normalized))
    for seq in _CJK_SEQ_RE.findall(normalized):
        if len(seq) <= 1:
            continue
        if len(seq) <= 4:
            tokens.append(seq)
        tokens.extend(seq[idx : idx + 2] for idx in range(len(seq) - 1))
        if len(seq) >= 3:
            tokens.extend(seq[idx : idx + 3] for idx in range(len(seq) - 2))

    return [token for token in tokens if token and token not in _STOP_TOKENS]
