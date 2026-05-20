from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import ENV_FILE, settings
from app.core.database import engine, initialize_database, is_postgres_db


def _mask(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "*" * len(value)
    return value[:4] + "*" * (len(value) - 8) + value[-4:]


def _check_database() -> dict:
    summary: dict[str, object] = {
        "database_url": settings.database_url,
        "dialect": engine.dialect.name,
        "postgres": is_postgres_db(),
    }
    initialize_database()
    with engine.connect() as conn:
        summary["documents"] = conn.execute(text("SELECT COUNT(*) FROM documents")).scalar_one()
        summary["chunks"] = conn.execute(text("SELECT COUNT(*) FROM chunks")).scalar_one()
        summary["query_logs"] = conn.execute(text("SELECT COUNT(*) FROM query_logs")).scalar_one()
        summary["document_artifacts"] = conn.execute(
            text("SELECT COUNT(*) FROM document_artifacts")
        ).scalar_one()
    return summary


def _check_runtime() -> dict:
    return {
        "app_name": settings.app_name,
        "app_env": settings.app_env,
        "log_level": settings.log_level,
        "default_top_k": settings.default_top_k,
        "embedding_dimensions": settings.embedding_dimensions,
        "embedding_configured": bool(
            settings.embedding_base_url and settings.embedding_model
        ),
        "embedding_base_url": settings.embedding_base_url,
        "embedding_model": settings.embedding_model,
        "embedding_api_key": _mask(settings.embedding_api_key),
        "llm_configured": bool(settings.llm_base_url and settings.llm_model),
        "llm_base_url": settings.llm_base_url,
        "llm_model": settings.llm_model,
        "llm_api_key": _mask(settings.llm_api_key),
        "env_file_loaded": ENV_FILE.exists(),
        "env_file_path": str(ENV_FILE),
    }


def _run_eval_preset(preset: str) -> dict:
    command = [sys.executable, "scripts/eval.py", preset]
    result = subprocess.run(
        command,
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return {
        "preset": preset,
        "returncode": result.returncode,
        "stdout": result.stdout.strip(),
        "stderr": result.stderr.strip(),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run a deployment-oriented preflight check for stock-RAG."
    )
    parser.add_argument(
        "--with-eval",
        action="store_true",
        help="Also run facts-smoke and smoke after environment and database checks.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full preflight report as JSON.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    report = {
        "runtime": _check_runtime(),
        "database": _check_database(),
        "evals": [],
        "warnings": [],
    }

    if not report["database"]["postgres"]:
        report["warnings"].append("DATABASE_URL is not PostgreSQL; SQLite is not recommended for landing.")
    if not report["runtime"]["embedding_configured"]:
        report["warnings"].append("Embedding endpoint is not configured; runtime will fall back to hash embeddings.")
    if not report["runtime"]["llm_configured"]:
        report["warnings"].append("LLM endpoint is not configured; runtime will answer in evidence-summary mode.")

    if args.with_eval:
        report["evals"].append(_run_eval_preset("facts-smoke"))
        report["evals"].append(_run_eval_preset("smoke"))

    failed_evals = [item for item in report["evals"] if item["returncode"] != 0]
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"app={report['runtime']['app_name']} env={report['runtime']['app_env']}")
        print(
            f"db={report['database']['dialect']} documents={report['database']['documents']} "
            f"chunks={report['database']['chunks']} artifacts={report['database']['document_artifacts']}"
        )
        print(
            f"embedding_configured={report['runtime']['embedding_configured']} "
            f"llm_configured={report['runtime']['llm_configured']} env_file_loaded={report['runtime']['env_file_loaded']}"
        )
        for warning in report["warnings"]:
            print(f"warning: {warning}")
        for item in report["evals"]:
            print(f"eval:{item['preset']} returncode={item['returncode']}")
            if item["stdout"]:
                print(item["stdout"])
            if item["stderr"]:
                print(item["stderr"])

    if failed_evals:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
