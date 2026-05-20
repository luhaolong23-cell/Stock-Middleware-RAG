from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from app.ingestion.parser import ParsedDocument


class MetadataExtractor:
    INDUSTRY_MAP_PATH = Path(__file__).resolve().parents[2] / "data" / "industry_map.json"
    INDUSTRY_PATTERNS: tuple[tuple[str, tuple[str, ...]], ...] = (
        ("银行", ("银行", "商业银行", "股份制银行", "金融服务")),
        ("保险", ("保险", "寿险", "财险")),
        ("白酒", ("白酒", "茅台酒", "酒类产品", "酿酒")),
        ("石油化工", ("石化", "炼化", "聚酯", "pta", "化工")),
        ("新能源电力与燃气", ("绿能", "风电", "光伏", "天然气", "燃气", "新能源发电", "售气")),
        ("建筑工程", ("核建", "建筑施工", "工程建设", "基建", "施工总承包", "核电工程")),
        ("物流运输", ("物流", "航运", "货运", "运输服务", "航道运输")),
        ("建材", ("玻璃纤维", "玻纤", "复合材料", "建材")),
        ("半导体", ("半导体", "硅片", "芯片", "集成电路")),
        ("传媒出版", ("出版", "传媒", "图书", "发行")),
        ("光电设备", ("光电", "光学", "检测设备", "成像设备")),
        ("橡胶", ("天然橡胶", "橡胶加工", "割胶")),
        ("商贸零售", ("零售", "百货", "商业运营", "商贸")),
    )

    def extract(self, parsed: ParsedDocument) -> dict:
        title = parsed.title
        content = parsed.text[:2000]
        ticker = self._extract_ticker(title) or self._extract_ticker(content)
        published_at = self._extract_date(content)
        return {
            "company": self._extract_company(title),
            "ticker": ticker,
            "industry": self._extract_industry(title, parsed.text, ticker=ticker),
            "published_at": published_at,
            "version": "v1",
        }

    def _extract_ticker(self, text: str) -> str | None:
        match = re.search(r"(?<!\d)(\d{6})(?!\d)", text)
        return match.group(1) if match else None

    def _extract_company(self, text: str) -> str | None:
        from_title = self._extract_company_from_title(text)
        if from_title:
            return from_title
        if "：" in text:
            return text.split("：", 1)[0].strip()[:64]
        if "-" in text:
            return text.split("-", 1)[0].strip()[:64]
        return None

    def _extract_company_from_title(self, text: str) -> str | None:
        tokens = [token.strip() for token in re.split(r"[_\-\s]+", text) if token.strip()]
        if not tokens:
            return None

        if re.fullmatch(r"\d{6}", tokens[0]):
            tokens = tokens[1:]

        report_markers = {
            "q1报",
            "q3报",
            "一季报",
            "三季报",
            "季报",
            "半年报",
            "年报",
        }
        company_tokens: list[str] = []
        for token in tokens:
            lowered = token.lower()
            if re.fullmatch(r"20\d{2}", token):
                break
            if lowered in report_markers:
                break
            if lowered.startswith("q") and lowered.endswith("报"):
                break
            if re.search(r"[\u4e00-\u9fff]", token):
                company_tokens.append(token)
                continue
            if re.fullmatch(r"[A-Za-z]{1,4}", token) and company_tokens:
                company_tokens.append(token)
                continue
            break

        if not company_tokens:
            return None
        return "".join(company_tokens)[:64]

    def _extract_date(self, text: str) -> datetime | None:
        match = re.search(r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})", text)
        if not match:
            return None
        year, month, day = [int(item) for item in match.groups()]
        try:
            return datetime(year, month, day)
        except ValueError:
            return None

    def _extract_industry(self, title: str, text: str, ticker: str | None = None) -> str | None:
        mapped = self._lookup_industry_map(ticker, title)
        if mapped:
            return mapped
        direct = self._extract_industry_from_label(text)
        if direct:
            return direct
        return self._infer_industry_from_keywords(title, text[:20000])

    def _lookup_industry_map(self, ticker: str | None, title: str) -> str | None:
        mapping = self._load_industry_map()
        if ticker and ticker in mapping:
            return mapping[ticker]
        title_ticker = self._extract_ticker(title)
        if title_ticker and title_ticker in mapping:
            return mapping[title_ticker]
        return None

    def _extract_industry_from_label(self, text: str) -> str | None:
        compact = self._compact_text(text[:20000])
        patterns = (
            r"(?:所属行业|公司所处行业|所处行业|行业分类)[:：]?(.*?)(?:主营业务|主要业务|经营情况|公司简介|报告期|$)",
        )
        for pattern in patterns:
            match = re.search(pattern, compact)
            if not match:
                continue
            candidate = match.group(1).strip("：:，,；;。 ")
            candidate = candidate[:24]
            normalized = self._canonicalize_industry(candidate)
            if normalized:
                return normalized
            if 1 < len(candidate) <= 16:
                return candidate
        return None

    def _infer_industry_from_keywords(self, title: str, text: str) -> str | None:
        title_compact = self._compact_text(title).lower()
        body_compact = self._compact_text(text).lower()
        best_industry: str | None = None
        best_score = 0
        for industry, keywords in self.INDUSTRY_PATTERNS:
            score = 0
            for keyword in keywords:
                token = keyword.lower()
                if token in title_compact:
                    score += 2
                if token in body_compact:
                    score += 2 if len(token) >= 3 else 1
            if score > best_score:
                best_industry = industry
                best_score = score
        return best_industry if best_score >= 2 else None

    def _canonicalize_industry(self, candidate: str) -> str | None:
        compact = self._compact_text(candidate).lower()
        if not compact:
            return None
        for industry, keywords in self.INDUSTRY_PATTERNS:
            if compact == industry.lower():
                return industry
            if any(keyword.lower() in compact for keyword in keywords):
                return industry
        return None

    def _compact_text(self, text: str) -> str:
        return re.sub(r"\s+", "", text or "")

    def _load_industry_map(self) -> dict[str, str]:
        cache = getattr(self.__class__, "_industry_map_cache", None)
        if cache is not None:
            return cache
        if not self.INDUSTRY_MAP_PATH.exists():
            cache = {}
        else:
            cache = json.loads(self.INDUSTRY_MAP_PATH.read_text(encoding="utf-8"))
        setattr(self.__class__, "_industry_map_cache", cache)
        return cache
