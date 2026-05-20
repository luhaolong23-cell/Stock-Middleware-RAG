from __future__ import annotations

from dataclasses import dataclass
import re
import subprocess
from pathlib import Path

from sqlalchemy.orm import Session

from app.ingestion.pipeline import IngestionPipeline


@dataclass
class DownloadTaskResult:
    stock: str
    pdf_path: str | None = None
    downloaded: bool = False
    ingested: bool = False
    document_id: int | None = None
    title: str | None = None
    chunk_count: int | None = None
    replaced_count: int | None = None
    strategy: str | None = None
    error: str | None = None


def download_latest_quarterly(
    stock: str,
    output_dir: Path,
    years: int = 1,
    timeout: int = 60000,
) -> Path:
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "stock-data-downloader",
        "--stock",
        stock,
        "--years",
        str(years),
        "--mode",
        "latest-quarterly",
        "--output",
        str(output_dir),
        "--timeout",
        str(timeout),
    ]
    completed = subprocess.run(
        cmd,
        input="y\n",
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"downloader exited with code {completed.returncode}")

    return find_latest_quarterly_pdf(output_dir, stock)


def ingest_pdf(
    db: Session,
    pdf_path: Path,
    overwrite: bool = True,
) -> dict:
    pipeline = IngestionPipeline(db)
    return pipeline.run(str(pdf_path), overwrite=overwrite)


def download_and_optionally_ingest(
    stock: str,
    output_dir: Path,
    years: int = 1,
    timeout: int = 60000,
    db: Session | None = None,
    ingest: bool = False,
    overwrite: bool = True,
) -> DownloadTaskResult:
    result = DownloadTaskResult(stock=stock)
    try:
        pdf_path = download_latest_quarterly(
            stock=stock,
            years=years,
            output_dir=output_dir,
            timeout=timeout,
        )
        result.pdf_path = str(pdf_path)
        result.downloaded = True

        if ingest:
            if db is None:
                raise RuntimeError("db session is required when ingest=True")
            ingest_result = ingest_pdf(
                db=db,
                pdf_path=pdf_path,
                overwrite=overwrite,
            )
            result.ingested = True
            result.document_id = ingest_result["document_id"]
            result.title = ingest_result["title"]
            result.chunk_count = ingest_result["chunk_count"]
            result.replaced_count = ingest_result["replaced_count"]
            result.strategy = ingest_result["strategy"]
    except Exception as exc:
        result.error = str(exc)
    return result


def download_latest_quarterly_batch(
    stocks: list[str],
    output_dir: Path,
    years: int = 1,
    timeout: int = 60000,
    db: Session | None = None,
    ingest: bool = False,
    overwrite: bool = True,
) -> list[DownloadTaskResult]:
    results: list[DownloadTaskResult] = []
    for stock in stocks:
        stock = stock.strip()
        if not stock:
            continue
        results.append(
            download_and_optionally_ingest(
                stock=stock,
                output_dir=output_dir,
                years=years,
                timeout=timeout,
                db=db,
                ingest=ingest,
                overwrite=overwrite,
            )
        )
    return results


def load_stock_list(path: Path) -> list[str]:
    items: list[str] = []
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        items.append(line)
    return items


def find_latest_quarterly_pdf(output_dir: Path, stock: str) -> Path:
    normalized_code = normalize_stock_code(stock)
    candidates = list(output_dir.glob("**/*_Q1报.pdf")) + list(
        output_dir.glob("**/*_Q3报.pdf")
    )
    if normalized_code:
        candidates = [path for path in candidates if path.name.startswith(normalized_code)]

    if not candidates:
        raise FileNotFoundError(
            f"no latest quarterly pdf found under {output_dir} for stock {stock}"
        )

    def sort_key(path: Path) -> tuple[int, int]:
        year_match = re.search(r"(20\d{2})", path.name)
        quarter_match = re.search(r"_Q([13])报\.pdf$", path.name)
        year = int(year_match.group(1)) if year_match else 0
        quarter = int(quarter_match.group(1)) if quarter_match else 0
        return year, quarter

    return sorted(candidates, key=sort_key, reverse=True)[0]


def normalize_stock_code(stock: str) -> str | None:
    digits = re.sub(r"\D", "", stock)
    if len(digits) == 6:
        return digits
    return None
