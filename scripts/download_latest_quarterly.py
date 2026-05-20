from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import Base, SessionLocal, engine
from app.tools.stock_downloader import download_and_optionally_ingest


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="下载并入库单只股票的最新季度财报"
    )
    parser.add_argument("stock", help="股票代码或公司名称")
    parser.add_argument(
        "--years",
        type=int,
        default=1,
        help="下载查询窗口，默认最近 1 年",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "data" / "latest-quarterly"),
        help="下载输出目录",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60000,
        help="下载超时毫秒数",
    )
    parser.add_argument(
        "--no-ingest",
        action="store_true",
        help="只下载，不入库",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="入库时不覆盖同类旧文档",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if args.no_ingest:
        result = download_and_optionally_ingest(
            stock=args.stock,
            years=args.years,
            output_dir=output_dir,
            timeout=args.timeout,
            ingest=False,
        )
    else:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            result = download_and_optionally_ingest(
                stock=args.stock,
                years=args.years,
                output_dir=output_dir,
                timeout=args.timeout,
                db=db,
                ingest=True,
                overwrite=not args.no_overwrite,
            )
        finally:
            db.close()

    if result.error:
        raise SystemExit(result.error)

    print(f"downloaded latest quarterly report: {result.pdf_path}")
    if result.ingested:
        print(
            "ingested "
            f"{result.title} -> {result.chunk_count} chunks "
            f"(replaced {result.replaced_count})"
        )


if __name__ == "__main__":
    main()
