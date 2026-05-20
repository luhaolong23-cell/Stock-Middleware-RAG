from __future__ import annotations

from app.retrieval.hybrid import ScoredChunk


def build_context(hits: list[ScoredChunk], limit: int = 3) -> str:
    blocks = []
    for index, hit in enumerate(hits[:limit], start=1):
        chunk = hit.chunk
        blocks.append(
            "\n".join(
                [
                    f"[{index}] {chunk.document.title}",
                    f"page: {chunk.page_number or 'unknown'}",
                    f"chunk_type: {chunk.chunk_type}",
                    f"section: {chunk.section_title or 'unknown'}",
                    f"table: {chunk.table_title or 'unknown'}",
                    f"source: {chunk.document.source}",
                    f"score: {hit.score:.6f}",
                    f"content: {chunk.content[:600]}",
                ]
            )
        )
    return "\n\n".join(blocks)


def build_answer_messages(query: str, hits: list[ScoredChunk], limit: int = 4) -> list[dict[str, str]]:
    context = build_context(hits, limit=limit)
    system_prompt = (
        "你是一个投研知识助手。"
        "只能基于给定证据回答，不允许补充证据中没有出现的事实。"
        "如果证据不足，要明确说证据不足。"
        "回答尽量简洁，使用中文。"
        "优先输出“结论：”“依据：”“来源：”三部分。"
    )
    user_prompt = (
        f"问题：{query}\n\n"
        f"证据：\n{context}\n\n"
        "请只基于上述证据回答。来源请引用证据编号，如[1][2]。"
    )
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]
