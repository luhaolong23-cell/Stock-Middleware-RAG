from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
JSON_PATH = PROJECT_ROOT / "tests" / "facts_eval_gold_manual_2026q1_26docs.json"
CSV_PATH = PROJECT_ROOT / "data" / "manual_truth" / "facts_gold_manual_2026q1_26docs.csv"


CORRECTIONS: dict[str, dict[str, dict[str, Any]]] = {
    "600036_招商银行_2026_Q1报": {
        "total_liabilities": {
            "value": "12,194,297",
            "expected_unit": "人民币百万元",
            "expected_numeric_value": 12194297.0,
            "expected_normalized_value_cny": 12194297000000.0,
        },
    },
    "600176_中国巨石_2026_Q1报": {
        "net_profit": {
            "value": "1,314,322,290.49",
            "expected_numeric_value": 1314322290.49,
            "expected_normalized_value_cny": 1314322290.49,
        },
    },
    "600281_华阳新材_2026_Q1报": {
        "net_profit": {
            "value": "90,278.35",
            "expected_numeric_value": 90278.35,
            "expected_normalized_value_cny": 90278.35,
        },
    },
    "600346_恒力石化_2026_Q1报": {
        "net_profit": {
            "value": "3,909,451,795.20",
            "expected_numeric_value": 3909451795.20,
            "expected_normalized_value_cny": 3909451795.20,
        },
    },
    "600428_中远海特_2026_Q1报": {
        "net_profit": {
            "value": "595,211,395.57",
            "expected_numeric_value": 595211395.57,
            "expected_normalized_value_cny": 595211395.57,
        },
    },
    "600519_贵州茅台_2026_Q1报": {
        "net_profit": {
            "value": "28,153,831,489.89",
            "expected_numeric_value": 28153831489.89,
            "expected_normalized_value_cny": 28153831489.89,
        },
    },
    "600725_云维股份_2026_Q1报": {
        "net_profit": {
            "value": "-1,610,014.01",
            "expected_numeric_value": -1610014.01,
            "expected_normalized_value_cny": -1610014.01,
        },
    },
    "601318_中国平安_2026_Q1报": {
        "net_profit": {
            "value": "33,263",
            "expected_numeric_value": 33263.0,
            "expected_normalized_value_cny": 33263000000.0,
        },
    },
    "601598_中国外运_2026_Q1报": {
        "net_profit": {
            "value": "733,904,809.25",
            "expected_numeric_value": 733904809.25,
            "expected_normalized_value_cny": 733904809.25,
        },
    },
    "601818_光大银行_2026_Q1报": {
        "net_profit": {
            "value": "11,521",
            "expected_unit": "人民币百万元",
            "expected_numeric_value": 11521.0,
            "expected_normalized_value_cny": 11521000000.0,
        },
        "total_liabilities": {
            "value": "6,624,131",
            "expected_unit": "人民币百万元",
            "expected_numeric_value": 6624131.0,
            "expected_normalized_value_cny": 6624131000000.0,
        },
        "operating_cash_flow": {
            "value": "(36,015)",
            "expected_unit": "人民币百万元",
            "expected_numeric_value": -36015.0,
            "expected_normalized_value_cny": -36015000000.0,
        },
    },
    "603058_永吉股份_2026_Q1报": {
        "net_profit": {
            "value": "-7,032,976.00",
            "expected_numeric_value": -7032976.0,
            "expected_normalized_value_cny": -7032976.0,
        },
    },
    "603117_万林物流_2026_Q1报": {
        "net_profit": {
            "value": "-6,086,021.24",
            "expected_numeric_value": -6086021.24,
            "expected_normalized_value_cny": -6086021.24,
        },
    },
    "688009_中国通号_2026_Q1报": {
        "net_profit": {
            "value": "615,961,768.27",
            "expected_numeric_value": 615961768.27,
            "expected_normalized_value_cny": 615961768.27,
        },
    },
    "688233_神工股份_2026_Q1报": {
        "net_profit": {
            "value": "28,034,827.66",
            "expected_numeric_value": 28034827.66,
            "expected_normalized_value_cny": 28034827.66,
        },
    },
}


CSV_FIELDS = [
    "document_title",
    "metric",
    "value",
    "expected_unit",
    "expected_numeric_value",
    "expected_normalized_value_cny",
]


def main() -> None:
    dataset = json.loads(JSON_PATH.read_text(encoding="utf-8"))

    for case in dataset.get("facts_cases", []):
        corrections = CORRECTIONS.get(case["document_title"])
        if not corrections:
            continue
        metrics = case.get("expected_metrics", {})
        for metric_key, patch in corrections.items():
            metric = metrics[metric_key]
            metric.update(patch)

    JSON_PATH.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    with CSV_PATH.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for case in dataset.get("facts_cases", []):
            title = case["document_title"]
            for metric, payload in case.get("expected_metrics", {}).items():
                writer.writerow(
                    {
                        "document_title": title,
                        "metric": metric,
                        "value": payload.get("value"),
                        "expected_unit": payload.get("expected_unit"),
                        "expected_numeric_value": payload.get("expected_numeric_value"),
                        "expected_normalized_value_cny": payload.get(
                            "expected_normalized_value_cny"
                        ),
                    }
                )


if __name__ == "__main__":
    main()
