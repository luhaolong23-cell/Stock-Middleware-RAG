from __future__ import annotations

from dataclasses import dataclass
import re

from app.ingestion.chunker import ChunkRecord, ChunkingBase
from app.ingestion.parser import ParsedElement


@dataclass
class _BufferedParagraph:
    content: str
    page_number: int | None
    section_title: str | None


class FinancialReportChunkerV2(ChunkingBase):
    def __init__(
        self,
        max_chars: int = 650,
        min_chars: int = 120,
        text_max_chars: int = 420,
        key_section_text_max_chars: int = 520,
        table_max_chars: int = 1400,
        table_rows_per_chunk: int = 12,
    ) -> None:
        super().__init__(max_chars=max_chars, min_chars=min_chars)
        self.text_max_chars = text_max_chars
        self.key_section_text_max_chars = key_section_text_max_chars
        self.table_max_chars = table_max_chars
        self.table_rows_per_chunk = table_rows_per_chunk

    def split_elements(self, elements: list[ParsedElement]) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        text_buffer: list[_BufferedParagraph] = []

        def flush_text_buffer() -> None:
            nonlocal text_buffer
            if not text_buffer:
                return
            chunks.extend(self._merge_text_buffer(text_buffer, len(chunks)))
            text_buffer = []

        for element in elements:
            if not element.content.strip():
                continue

            if element.element_type == "text":
                text_buffer.append(
                    _BufferedParagraph(
                        content=element.content.strip(),
                        page_number=element.page_number,
                        section_title=element.section_title,
                    )
                )
                continue

            flush_text_buffer()
            if element.element_type == "table":
                chunks.extend(self._split_table_element(element, len(chunks)))
                continue

            chunks.append(
                self._build_chunk(
                    chunk_index=len(chunks),
                    chunk_type=element.element_type,
                    section_title=element.section_title,
                    content=element.content,
                    page_number=element.page_number,
                    table_title=element.table_title,
                    figure_title=element.figure_title,
                )
            )

        flush_text_buffer()
        return chunks

    def _merge_text_buffer(
        self, paragraphs: list[_BufferedParagraph], start_index: int
    ) -> list[ChunkRecord]:
        chunks: list[ChunkRecord] = []
        buffer: list[str] = []
        section_title: str | None = None
        page_number: int | None = None

        for paragraph in paragraphs:
            current_section = paragraph.section_title or section_title
            if (
                section_title is not None
                and current_section is not None
                and current_section != section_title
                and buffer
            ):
                chunks.append(
                    self._build_chunk(
                        chunk_index=start_index + len(chunks),
                        chunk_type="text",
                        section_title=section_title,
                        content="\n".join(buffer),
                        page_number=page_number,
                    )
                )
                buffer = []

            section_title = current_section
            page_number = page_number or paragraph.page_number

            text_units = self._split_text_units(paragraph.content, current_section)
            if not text_units:
                continue

            max_chars = self._preferred_text_max_chars(current_section)
            for text_unit in text_units:
                candidate = "\n".join([*buffer, text_unit]).strip()
                if len(candidate) > max_chars and buffer:
                    chunks.append(
                        self._build_chunk(
                            chunk_index=start_index + len(chunks),
                            chunk_type="text",
                            section_title=section_title,
                            content="\n".join(buffer),
                            page_number=page_number,
                        )
                    )
                    buffer = [text_unit]
                    page_number = paragraph.page_number
                else:
                    buffer.append(text_unit)
                    page_number = page_number or paragraph.page_number

        if buffer:
            chunks.append(
                self._build_chunk(
                    chunk_index=start_index + len(chunks),
                    chunk_type="text",
                    section_title=section_title,
                    content="\n".join(buffer),
                    page_number=page_number,
                )
            )

        return chunks

    def _split_table_element(
        self, element: ParsedElement, start_index: int
    ) -> list[ChunkRecord]:
        normalized_rows = [row.strip() for row in element.content.splitlines() if row.strip()]
        if not normalized_rows:
            return []

        if not self._is_large_table(normalized_rows, element.content):
            return [
                self._build_chunk(
                    chunk_index=start_index,
                    chunk_type="table",
                    section_title=element.section_title,
                    content=element.content,
                    page_number=element.page_number,
                    table_title=element.table_title,
                    figure_title=element.figure_title,
                )
            ]

        header_rows, body_rows = self._split_table_header_rows(normalized_rows)
        header_text = "\n".join(header_rows)
        chunks: list[ChunkRecord] = []

        overview_lines = header_rows + body_rows[: min(4, len(body_rows))]
        if len(body_rows) > 4:
            overview_lines.append(
                f"... total_rows={len(body_rows)} grouped_rows_per_chunk={self.table_rows_per_chunk}"
            )
        chunks.append(
            self._build_chunk(
                chunk_index=start_index,
                chunk_type="table",
                section_title=element.section_title,
                content="\n".join(overview_lines),
                page_number=element.page_number,
                table_title=element.table_title,
                figure_title=element.figure_title,
            )
        )

        for group_index, offset in enumerate(
            range(0, len(body_rows), self.table_rows_per_chunk), start=1
        ):
            rows = body_rows[offset : offset + self.table_rows_per_chunk]
            table_title = element.table_title
            if table_title:
                table_title = f"{table_title} 行组{group_index}"
            content = "\n".join([header_text, *rows]) if header_text else "\n".join(rows)
            chunks.append(
                self._build_chunk(
                    chunk_index=start_index + len(chunks),
                    chunk_type="table",
                    section_title=element.section_title,
                    content=content,
                    page_number=element.page_number,
                    table_title=table_title,
                    figure_title=element.figure_title,
                )
            )

        return chunks

    def _split_table_header_rows(self, rows: list[str]) -> tuple[list[str], list[str]]:
        if len(rows) <= 2:
            return rows[:1], rows[1:]

        header_rows = [rows[0]]
        second_row = rows[1]
        if second_row.count("|") >= rows[0].count("|") - 1:
            header_rows.append(second_row)
            body_rows = rows[2:]
        else:
            body_rows = rows[1:]
        return header_rows, body_rows

    def _is_large_table(self, rows: list[str], content: str) -> bool:
        return len(rows) > self.table_rows_per_chunk or len(content) > self.table_max_chars

    def _normalize_paragraph(self, content: str) -> str:
        compact = re.sub(r"\s+", " ", content).strip()
        return compact

    def _preferred_text_max_chars(self, section_title: str | None) -> int:
        if section_title and self._is_key_section(section_title):
            return self.key_section_text_max_chars
        return self.text_max_chars

    def _split_text_units(
        self, content: str, section_title: str | None
    ) -> list[str]:
        paragraph = self._normalize_paragraph(content)
        if not paragraph:
            return []

        max_chars = self._preferred_text_max_chars(section_title)
        if len(paragraph) <= max_chars:
            return [paragraph]

        sentences = self._split_sentences(paragraph)
        units: list[str] = []
        buffer = ""
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            if len(sentence) > max_chars:
                if buffer:
                    units.append(buffer)
                    buffer = ""
                units.extend(self._split_long_sentence(sentence, max_chars))
                continue

            candidate = f"{buffer} {sentence}".strip() if buffer else sentence
            if len(candidate) > max_chars and buffer:
                units.append(buffer)
                buffer = sentence
            else:
                buffer = candidate

        if buffer:
            units.append(buffer)
        return units or [paragraph]

    def _split_sentences(self, content: str) -> list[str]:
        parts = re.split(r"(?<=[。！？；;])\s*", content)
        return [part.strip() for part in parts if part.strip()]

    def _split_long_sentence(self, content: str, max_chars: int) -> list[str]:
        clauses = re.split(r"(?<=[，、：:,])\s*", content)
        units: list[str] = []
        buffer = ""
        for clause in clauses:
            clause = clause.strip()
            if not clause:
                continue

            candidate = f"{buffer}{clause}" if buffer else clause
            if len(candidate) <= max_chars:
                buffer = candidate
                continue

            if buffer:
                units.append(buffer)
                buffer = ""

            if len(clause) <= max_chars:
                buffer = clause
                continue

            for start in range(0, len(clause), max_chars):
                units.append(clause[start : start + max_chars])

        if buffer:
            units.append(buffer)
        return units

    def _build_chunk(
        self,
        chunk_index: int,
        chunk_type: str,
        section_title: str | None,
        content: str,
        page_number: int | None = None,
        table_title: str | None = None,
        figure_title: str | None = None,
    ) -> ChunkRecord:
        compact = content.strip()
        if chunk_type == "table" and table_title and table_title not in compact:
            compact = "\n".join((table_title, compact))
        if chunk_type == "table":
            inferred_label = self._infer_table_label(
                content=compact,
                section_title=section_title,
                table_title=table_title,
            )
            if inferred_label and inferred_label not in compact:
                compact = "\n".join((inferred_label, compact))
        if self._should_expand_short_text(chunk_type, compact, section_title):
            page_prefix = f"[第{page_number}页]" if page_number else ""
            title_prefix = section_title or ""
            compact = "\n".join(
                part for part in (page_prefix, title_prefix, compact) if part
            )
        return ChunkRecord(
            chunk_index=chunk_index,
            chunk_type=chunk_type,
            section_title=section_title,
            content=compact,
            token_count=len(compact),
            page_number=page_number,
            table_title=table_title,
            figure_title=figure_title,
        )

    def _infer_table_label(
        self,
        content: str,
        section_title: str | None,
        table_title: str | None,
    ) -> str | None:
        normalized = re.sub(r"\s+", "", "\n".join(part for part in (section_title, table_title, content) if part))

        if "主要会计数据" in normalized or "主要财务指标" in normalized:
            return "主要会计数据和财务指标"

        if self._contains_all(
            normalized,
            ("经营活动产生的现金流量", "投资活动产生的现金流量"),
        ) or "现金及现金等价物净增加额" in normalized:
            return "合并现金流量表"

        if self._contains_all(
            normalized,
            ("流动资产", "非流动资产"),
        ) or self._contains_all(
            normalized,
            ("资产总计", "负债合计"),
        ):
            return "合并资产负债表"

        if (
            "营业总收入" in normalized or "营业收入" in normalized
        ) and any(term in normalized for term in ("营业利润", "利润总额", "净利润")):
            return "合并利润表"

        return None

    def _contains_all(self, haystack: str, needles: tuple[str, ...]) -> bool:
        return all(needle in haystack for needle in needles)
