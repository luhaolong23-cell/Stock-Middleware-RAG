from __future__ import annotations

from dataclasses import dataclass
import re

@dataclass
class ChunkRecord:
    chunk_index: int
    chunk_type: str
    section_title: str | None
    content: str
    token_count: int
    page_number: int | None = None
    table_title: str | None = None
    figure_title: str | None = None


class ChunkingBase:
    KEY_SECTION_HINTS = (
        "重要提示",
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
        "递延所得税",
        "内部开发支出",
    )

    def __init__(self, max_chars: int = 800, min_chars: int = 120) -> None:
        self.max_chars = max_chars
        self.min_chars = min_chars

    def _is_key_section(self, section_title: str) -> bool:
        return any(hint in section_title for hint in self.KEY_SECTION_HINTS)

    def _should_expand_short_text(
        self, chunk_type: str, content: str, section_title: str | None
    ) -> bool:
        if chunk_type != "text" or not section_title:
            return False
        if len(content) >= 80:
            return False
        if content.startswith(section_title):
            return False
        short_answer_markers = ("否", "是", "不适用", "适用", "√适用□不适用", "□适用√不适用")
        if content in short_answer_markers:
            return True
        if len(section_title) >= 20:
            return True
        return not any(punct in content for punct in ("。", "！", "？", "；"))
