from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.database import Base, SessionLocal, engine
from app.tools.stock_downloader import (
    download_latest_quarterly_batch,
    load_stock_list,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="批量下载并可选入库最新季度财报")
    parser.add_argument(
        "stocks",
        nargs="*",
        help="股票代码或公司名称列表",
    )
    parser.add_argument(
        "--stock-file",
        help="股票列表文件，每行一个代码或名称",
    )
    parser.add_argument(
        "--years",
        type=int,
        default=1,
        help="下载查询窗口，默认最近 1 年",
    )
    parser.add_argument(
        "--output",
        default=str(PROJECT_ROOT / "data" / "latest-quarterly-batch"),
        help="下载输出目录",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=60000,
        help="下载超时毫秒数",
    )
    parser.add_argument(
        "--ingest",
        action="store_true",
        help="下载后直接入库，默认只下载不入库",
    )
    parser.add_argument(
        "--no-overwrite",
        action="store_true",
        help="入库时不覆盖同类旧文档",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    stocks = list(args.stocks)
    if args.stock_file:
        stocks.extend(load_stock_list(Path(args.stock_file).expanduser().resolve()))
    stocks = [stock.strip() for stock in stocks if stock.strip()]
    if not stocks:
        raise SystemExit("no stocks provided")

    output_dir = Path(args.output).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    results = []
    if not args.ingest:
        results = download_latest_quarterly_batch(
            stocks=stocks,
            output_dir=output_dir,
            years=args.years,
            timeout=args.timeout,
            ingest=False,
        )
    else:
        Base.metadata.create_all(bind=engine)
        db = SessionLocal()
        try:
            results = download_latest_quarterly_batch(
                stocks=stocks,
                output_dir=output_dir,
                years=args.years,
                timeout=args.timeout,
                db=db,
                ingest=True,
                overwrite=not args.no_overwrite,
            )
        finally:
            db.close()

    success = [item for item in results if not item.error]
    failed = [item for item in results if item.error]
    payload = {
        "total": len(results),
        "success": len(success),
        "failed": len(failed),
        "results": [item.__dict__ for item in results],
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
