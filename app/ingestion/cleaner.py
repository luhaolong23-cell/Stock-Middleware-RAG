from __future__ import annotations

import re


class TextCleaner:
    def clean(self, text: str) -> str:
        lines = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if self._is_noise(line):
                continue
            lines.append(line)

        cleaned = "\n".join(lines)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()

    def _is_noise(self, line: str) -> bool:
        if re.fullmatch(r"\d+\s*/\s*\d+", line):
            return True
        if self._is_report_header(line):
            return True
        if self._is_toc_line(line):
            return True
        if line.startswith("请务必阅读正文之后的"):
            return True
        if line.startswith("免责声明") and len(line) > 12:
            return True
        return False

    def _is_report_header(self, line: str) -> bool:
        return (
            "股份有限公司" in line
            and "报告" in line
            and len(line) <= 40
            and not line.endswith(("。", "：", ":"))
        )

    def _is_toc_line(self, line: str) -> bool:
        return bool(
            re.search(r"[\.。·…]{8,}\s*\d+\s*$", line)
            or re.search(r"[\.。·…]{8,}\s*\d+.*$", line)
        )
