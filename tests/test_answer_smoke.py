from __future__ import annotations

import json
import os
from pathlib import Path

from scripts.eval_layers import eval_answer_cases


def test_answer_smoke_regression() -> None:
    assert os.environ.get("DATABASE_URL"), (
        "DATABASE_URL must point to the populated PostgreSQL database."
    )

    dataset_path = Path(__file__).with_name("answer_eval_smoke.json")
    dataset = json.loads(dataset_path.read_text(encoding="utf-8"))
    result = eval_answer_cases(dataset["answer_cases"])

    assert result["passed"] == result["total"], json.dumps(result, ensure_ascii=False, indent=2)
