from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any

import fitz


@dataclass
class ParsedElement:
    element_type: str
    content: str
    page_number: int
    section_title: str | None = None
    table_title: str | None = None
    figure_title: str | None = None


@dataclass
class ParsedDocument:
    title: str
    source: str
    doc_type: str
    text: str
    elements: list[ParsedElement] = field(default_factory=list)


class DocumentParser:
    SECTION_KEYWORDS = (
        "风险提示",
        "重大风险",
        "公司面临的风险",
        "管理层讨论与分析",
        "经营情况讨论与分析",
        "董事会报告",
        "财务报告",
        "会计数据和财务指标",
        "主要会计数据",
        "主营业务分析",
        "核心竞争力分析",
        "行业情况",
        "重要事项",
    )
    TABLE_ROW_HEADING_KEYWORDS = (
        "期初余额",
        "期末余额",
        "期初账面价值",
        "本期增加金额",
        "本期减少金额",
        "账面价值",
        "账面余额",
        "累计摊销",
        "减值准备",
        "内部开发支出",
    )
    GENERIC_TABLE_TITLES = {
        "项目",
        "名称",
        "合计",
        "任公司",
        "币种：人民币",
        "单位：元",
        "√适用□不适用",
        "□适用√不适用",
        "□不适用",
        "正在办理中",
    }
    STRONG_HEADING_PATTERNS = (
        r"^[一二三四五六七八九十]+、",
        r"^第[一二三四五六七八九十]+节",
        r"^\d+、",
        r"^[（(]\d+[）)]",
        r"^\d+\.(?!\d)",
    )

    def parse(self, file_path: str) -> ParsedDocument:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"file not found: {file_path}")

        suffix = path.suffix.lower()
        title = path.stem

        if suffix in {".md", ".txt"}:
            text = path.read_text(encoding="utf-8")
            elements = [ParsedElement(element_type="text", content=text, page_number=1)]
        elif suffix in {".html", ".htm"}:
            text = path.read_text(encoding="utf-8")
            elements = [ParsedElement(element_type="text", content=text, page_number=1)]
        elif suffix == ".pdf":
            elements = self._parse_pdf_elements(path)
            text = self._merge_text_elements(elements)
        else:
            text = path.read_text(encoding="utf-8", errors="ignore")
            elements = [ParsedElement(element_type="text", content=text, page_number=1)]

        return ParsedDocument(
            title=title,
            source=str(path),
            doc_type=suffix.lstrip(".") or "unknown",
            text=text,
            elements=elements,
        )

    def _parse_pdf_elements(self, path: Path) -> list[ParsedElement]:
        elements: list[ParsedElement] = []
        current_section: str | None = None
        last_table_title_by_section: dict[str, str] = {}
        last_strong_table_title: str | None = None
        with fitz.open(path) as doc:
            for page_index, page in enumerate(doc, start=1):
                positioned_lines = self._extract_positioned_lines(page)
                lines = [line for _y, line in positioned_lines]
                is_toc_page = self._is_toc_page(lines)
                first_table_top = self._first_table_top(page)
                page_section = (
                    self._detect_page_section(positioned_lines, first_table_top)
                    or current_section
                )
                table_elements = self._extract_table_elements(
                    page, page_index, lines, positioned_lines, page_section
                )
                table_elements, last_strong_table_title = self._stabilize_table_titles(
                    table_elements,
                    last_table_title_by_section,
                    last_strong_table_title,
                )
                table_bboxes = self._extract_table_bboxes(page)
                text = self._extract_page_text(page, table_bboxes)
                if text and not is_toc_page:
                    elements.append(
                        ParsedElement(
                            element_type="text",
                            content=text,
                            page_number=page_index,
                            section_title=page_section,
                        )
                    )

                elements.extend(table_elements)
                elements.extend(self._extract_image_elements(page, page_index, lines, page_section))
                current_section = self._page_tail_section(table_elements, page_section) or current_section

        return elements

    def _extract_page_text(
        self,
        page: fitz.Page,
        table_bboxes: list[tuple[float, float, float, float]],
    ) -> str:
        page_dict: dict[str, Any] = page.get_text("dict")
        text_blocks: list[tuple[float, float, str]] = []
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            bbox = self._normalize_bbox(block.get("bbox"))
            if not bbox:
                continue
            if self._block_overlaps_table(bbox, table_bboxes):
                continue

            lines: list[str] = []
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(span.get("text", "") for span in spans)
                compact = re.sub(r"\s+", " ", text).strip()
                if compact:
                    lines.append(compact)

            block_text = "\n".join(lines).strip()
            if not block_text:
                continue
            text_blocks.append((bbox[1], bbox[0], block_text))

        text_blocks.sort(key=lambda item: (item[0], item[1]))
        return "\n".join(block_text for _y, _x, block_text in text_blocks).strip()

    def _extract_table_elements(
        self,
        page: fitz.Page,
        page_number: int,
        lines: list[str],
        positioned_lines: list[tuple[float, str]],
        section_title: str | None,
    ) -> list[ParsedElement]:
        if self._is_toc_page(lines):
            return []
        if not hasattr(page, "find_tables"):
            return []

        try:
            table_finder = page.find_tables()
        except Exception:
            return []

        table_titles = self._extract_titles(lines, prefix="表")
        table_elements: list[ParsedElement] = []
        for index, table in enumerate(getattr(table_finder, "tables", []), start=1):
            table_text = self._table_to_text(table.extract())
            if not table_text:
                continue
            table_top = self._table_top(table)
            table_section = self._nearest_section_before(
                positioned_lines,
                table_top,
                fallback=section_title,
            )
            explicit_title = table_titles[index - 1] if index - 1 < len(table_titles) else None
            caption_title = self._table_caption_before(positioned_lines, table_top)
            inferred_title = self._infer_table_title(table_text)
            table_title = self._pick_table_title(
                explicit_title=explicit_title,
                caption_title=caption_title,
                inferred_title=inferred_title,
                section_title=table_section,
                page_number=page_number,
                index=index,
                table_top=table_top,
            )
            table_elements.append(
                ParsedElement(
                    element_type="table",
                    content=table_text,
                    page_number=page_number,
                    section_title=table_section,
                    table_title=table_title,
                )
            )
        return table_elements

    def _extract_image_elements(
        self,
        page: fitz.Page,
        page_number: int,
        lines: list[str],
        section_title: str | None,
    ) -> list[ParsedElement]:
        image_refs = page.get_images(full=True)
        if not image_refs:
            return []

        figure_titles = self._extract_titles(lines, prefix="图")
        image_elements: list[ParsedElement] = []
        for index, _image_ref in enumerate(image_refs, start=1):
            figure_title = (
                figure_titles[index - 1]
                if index - 1 < len(figure_titles)
                else self._find_figure_caption("\n".join(lines))
            )
            content = figure_title or f"Image block detected on page {page_number}."
            image_elements.append(
                ParsedElement(
                    element_type="image",
                    content=content,
                    page_number=page_number,
                    section_title=section_title,
                    figure_title=figure_title or f"Figure {index} on page {page_number}",
                )
            )
        return image_elements

    def _merge_text_elements(self, elements: list[ParsedElement]) -> str:
        parts = [element.content for element in elements if element.element_type == "text"]
        return "\n\n".join(part for part in parts if part.strip())

    def _table_to_text(self, rows: list[list[str | None]]) -> str:
        normalized_rows = []
        for row in rows:
            cells = [(cell or "").strip() for cell in row]
            if any(cells):
                normalized_rows.append(" | ".join(cells))
        return "\n".join(normalized_rows)

    def _infer_table_title(self, table_text: str) -> str:
        first_line = table_text.splitlines()[0].strip() if table_text.splitlines() else ""
        if first_line:
            first_cell = first_line.split("|", 1)[0].strip()
            candidate = self._clean_title_candidate(first_cell or first_line)
            return candidate[:120]
        return ""

    def _clean_title_candidate(self, text: str) -> str:
        candidate = re.sub(r"\s+", " ", text).strip(" |：:。.")
        if not candidate:
            return ""
        if re.fullmatch(r"[\d,.\-/]+", candidate):
            return ""
        if len(candidate) < 4:
            return ""
        if len(candidate) > 40:
            return candidate[:40]
        return candidate

    def _find_figure_caption(self, text: str) -> str | None:
        for line in text.splitlines():
            compact = line.strip()
            if compact.startswith(("图", "Figure", "figure")):
                return compact[:120]
        return None

    def _extract_positioned_lines(self, page: fitz.Page) -> list[tuple[float, str]]:
        page_dict: dict[str, Any] = page.get_text("dict")
        raw_lines: list[tuple[float, str]] = []
        for block in page_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                text = "".join(span.get("text", "") for span in spans)
                compact = re.sub(r"\s+", " ", text).strip()
                if not compact:
                    continue
                bbox = line.get("bbox") or block.get("bbox") or (0, 0, 0, 0)
                raw_lines.append((float(bbox[1]), compact))

        raw_lines.sort(key=lambda item: item[0])

        normalized: list[tuple[float, str]] = []
        index = 0
        while index < len(raw_lines):
            y_pos, line = raw_lines[index]
            if (
                self._is_incomplete_heading(line)
                and index + 1 < len(raw_lines)
                and len(raw_lines[index + 1][1]) <= 40
            ):
                normalized.append((y_pos, f"{line}{raw_lines[index + 1][1]}"))
                index += 2
                continue
            normalized.append((y_pos, line))
            index += 1
        return normalized

    def _should_skip_text_element(
        self, page_text: str, table_elements: list[ParsedElement]
    ) -> bool:
        if not table_elements:
            return False

        page_text_length = len(re.sub(r"\s+", "", page_text))
        table_text_length = sum(
            len(re.sub(r"\s+", "", element.content)) for element in table_elements
        )
        short_line_count = sum(
            1
            for line in page_text.splitlines()
            if 0 < len(line.strip()) <= 20
        )
        dense_short_lines = short_line_count >= 12
        duplicate_ratio = (
            table_text_length / max(page_text_length, 1)
            if page_text_length
            else 0.0
        )

        return len(table_elements) >= 2 or dense_short_lines or duplicate_ratio >= 0.45

    def _normalize_lines(self, text: str) -> list[str]:
        raw_lines = []
        for raw_line in text.splitlines():
            line = re.sub(r"\s+", " ", raw_line).strip()
            if line:
                raw_lines.append(line)

        normalized: list[str] = []
        index = 0
        while index < len(raw_lines):
            line = raw_lines[index]
            if (
                self._is_incomplete_heading(line)
                and index + 1 < len(raw_lines)
                and len(raw_lines[index + 1]) <= 40
            ):
                normalized.append(f"{line}{raw_lines[index + 1]}")
                index += 2
                continue
            normalized.append(line)
            index += 1
        return normalized

    def _table_top(self, table: Any) -> float:
        bbox = getattr(table, "bbox", None)
        if not bbox:
            return 0.0
        return float(bbox[1])

    def _extract_table_bboxes(self, page: fitz.Page) -> list[tuple[float, float, float, float]]:
        if not hasattr(page, "find_tables"):
            return []
        try:
            table_finder = page.find_tables()
        except Exception:
            return []

        bboxes: list[tuple[float, float, float, float]] = []
        for table in getattr(table_finder, "tables", []):
            bbox = self._normalize_bbox(getattr(table, "bbox", None))
            if bbox:
                bboxes.append(bbox)
        return bboxes

    def _normalize_bbox(
        self, bbox: Any
    ) -> tuple[float, float, float, float] | None:
        if not bbox or len(bbox) != 4:
            return None
        x0, y0, x1, y1 = bbox
        return float(x0), float(y0), float(x1), float(y1)

    def _block_overlaps_table(
        self,
        block_bbox: tuple[float, float, float, float],
        table_bboxes: list[tuple[float, float, float, float]],
    ) -> bool:
        return any(
            self._bbox_overlap_ratio(block_bbox, table_bbox) >= 0.35
            for table_bbox in table_bboxes
        )

    def _bbox_overlap_ratio(
        self,
        bbox_a: tuple[float, float, float, float],
        bbox_b: tuple[float, float, float, float],
    ) -> float:
        ax0, ay0, ax1, ay1 = bbox_a
        bx0, by0, bx1, by1 = bbox_b
        overlap_w = max(0.0, min(ax1, bx1) - max(ax0, bx0))
        overlap_h = max(0.0, min(ay1, by1) - max(ay0, by0))
        if overlap_w <= 0 or overlap_h <= 0:
            return 0.0

        overlap_area = overlap_w * overlap_h
        block_area = max((ax1 - ax0) * (ay1 - ay0), 1.0)
        return overlap_area / block_area

    def _first_table_top(self, page: fitz.Page) -> float | None:
        if not hasattr(page, "find_tables"):
            return None
        try:
            table_finder = page.find_tables()
        except Exception:
            return None

        tops = [
            self._table_top(table)
            for table in getattr(table_finder, "tables", [])
            if self._table_top(table) > 0
        ]
        return min(tops) if tops else None

    def _nearest_section_before(
        self,
        positioned_lines: list[tuple[float, str]],
        target_y: float,
        fallback: str | None,
    ) -> str | None:
        current_section = (
            fallback if fallback and not self._looks_like_table_row_heading(fallback) else None
        )
        for y_pos, line in positioned_lines:
            if y_pos > target_y:
                break
            if self._looks_like_section_heading(line):
                current_section = self._normalize_heading(line)
        return current_section

    def _detect_page_section(
        self,
        positioned_lines: list[tuple[float, str]],
        first_table_top: float | None,
    ) -> str | None:
        candidate_lines = positioned_lines[:40]
        if first_table_top is not None:
            candidate_lines = [
                (y_pos, line)
                for y_pos, line in positioned_lines
                if y_pos < first_table_top - 6
            ][:40]
        for _y_pos, line in candidate_lines:
            if self._is_toc_line(line):
                continue
            if self._looks_like_section_heading(line):
                return self._normalize_heading(line)
        return None

    def _extract_titles(self, lines: list[str], prefix: str) -> list[str]:
        titles: list[str] = []
        for line in lines:
            if line.startswith(prefix) and len(line) <= 120:
                titles.append(line[:120])
        return titles

    def _looks_like_section_heading(self, line: str) -> bool:
        if len(line) > 120:
            return False
        if self._is_report_title_line(line):
            return False
        if self._is_toc_line(line):
            return False
        if re.fullmatch(r"\d+\s*/\s*\d+", line):
            return False
        if re.fullmatch(r"\d+(?:\.\d+)?", line):
            return False
        if re.fullmatch(r"\d+(?:\.\d+)?%", line):
            return False
        if self._looks_like_table_row_heading(line):
            return False
        if any(keyword in line for keyword in self.SECTION_KEYWORDS):
            return True
        return any(re.match(pattern, line) for pattern in self.STRONG_HEADING_PATTERNS)

    def _is_incomplete_heading(self, line: str) -> bool:
        incomplete_patterns = (
            r"^[一二三四五六七八九十]+、$",
            r"^第[一二三四五六七八九十]+节$",
            r"^\(?[一二三四五六七八九十]+\)$",
            r"^\d+\.$",
        )
        return any(re.match(pattern, line) for pattern in incomplete_patterns)

    def _is_report_title_line(self, line: str) -> bool:
        report_keywords = ("年度报告", "半年度报告", "季度报告")
        return (
            any(keyword in line for keyword in report_keywords)
            and len(line) <= 40
            and "真实性" not in line
            and "完整性" not in line
        )

    def _is_toc_line(self, line: str) -> bool:
        return bool(re.search(r"[\.。·…]{8,}\s*\d+\s*$", line))

    def _is_toc_page(self, lines: list[str]) -> bool:
        return sum(1 for line in lines if self._is_toc_line(line)) >= 4

    def _looks_like_table_row_heading(self, line: str) -> bool:
        if line in self.GENERIC_TABLE_TITLES:
            return True
        return any(keyword in line for keyword in self.TABLE_ROW_HEADING_KEYWORDS)

    def _table_caption_before(
        self, positioned_lines: list[tuple[float, str]], table_top: float
    ) -> str | None:
        for y_pos, line in reversed(positioned_lines):
            if y_pos >= table_top:
                continue
            if table_top - y_pos > 90:
                break
            if self._is_toc_line(line) or self._is_report_title_line(line):
                continue
            if self._looks_like_section_heading(line):
                break
            candidate = self._clean_title_candidate(line)
            if candidate and not self._is_weak_table_title(candidate):
                return candidate
        return None

    def _pick_table_title(
        self,
        explicit_title: str | None,
        caption_title: str | None,
        inferred_title: str | None,
        section_title: str | None,
        page_number: int,
        index: int,
        table_top: float,
    ) -> str:
        for candidate in (explicit_title, caption_title, inferred_title):
            cleaned = self._clean_title_candidate(candidate or "")
            if cleaned and not self._is_weak_table_title(cleaned):
                return cleaned[:120]
        if (
            section_title
            and not self._looks_like_table_row_heading(section_title)
            and not self._is_weak_table_title(section_title)
        ):
            return f"{section_title} 第{page_number}页表{index}"
        if table_top <= 110:
            return ""
        return f"第{page_number}页表{index}"

    def _is_weak_table_title(self, title: str) -> bool:
        cleaned = re.sub(r"\s+", " ", title).strip(" |：:。.")
        if not cleaned:
            return True
        if cleaned in self.GENERIC_TABLE_TITLES:
            return True
        if cleaned.startswith(("单位：", "单位:", "币种：", "币种:")):
            return True
        if re.fullmatch(r"[√□]?(?:适用)?[√□]?(?:不适用)?", cleaned):
            return True
        if re.fullmatch(r"[\d,.\-/]+", cleaned):
            return True
        if self._looks_like_table_row_heading(cleaned):
            return True
        if re.fullmatch(r"[（(]?\d+[）)].*", cleaned):
            return True
        return False

    def _stabilize_table_titles(
        self,
        table_elements: list[ParsedElement],
        last_table_title_by_section: dict[str, str],
        last_strong_table_title: str | None,
    ) -> tuple[list[ParsedElement], str | None]:
        for element in table_elements:
            section_key = element.section_title or "__default__"
            previous_title = last_table_title_by_section.get(section_key)
            if self._is_weak_table_title(element.table_title or ""):
                if previous_title:
                    element.table_title = f"{previous_title}（续）"
                elif last_strong_table_title:
                    element.table_title = f"{last_strong_table_title}（续）"
            else:
                last_table_title_by_section[section_key] = element.table_title or ""
                last_strong_table_title = element.table_title or last_strong_table_title
        return table_elements, last_strong_table_title

    def _normalize_heading(self, line: str) -> str:
        heading = re.sub(r"\s+", " ", line).strip()
        if re.match(r"^\d+\.(?!\d)", heading):
            sentence_parts = re.split(r"[。；;:：]", heading, maxsplit=1)
            heading = sentence_parts[0].strip()
        return heading[:120]

    def _page_tail_section(
        self,
        table_elements: list[ParsedElement],
        page_section: str | None,
    ) -> str | None:
        for element in reversed(table_elements):
            if element.section_title and not self._looks_like_table_row_heading(
                element.section_title
            ):
                return element.section_title
        return page_section
