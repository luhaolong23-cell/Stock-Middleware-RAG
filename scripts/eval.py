from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval_layers import main as eval_layers_main


PRESET_DATASETS: dict[str, tuple[str, str]] = {
    "sample": ("tests/layered_eval.sample.json", "all"),
    "smoke": ("tests/answer_eval_smoke.json", "answer"),
    "facts-smoke": ("tests/facts_eval_smoke.json", "facts"),
    "facts-full": ("tests/facts_eval_full.json", "facts"),
    "facts-2026q1": ("tests/facts_eval_2026q1_26docs.json", "facts"),
    "answer": ("tests/answer_eval_2026q1_22docs.json", "answer"),
    "answer-full": ("tests/answer_eval_full_2026q1_22docs.json", "answer"),
    "retrieval": ("tests/retrieval_eval_2026q1_22docs.json", "retrieval"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Unified evaluation entrypoint for parse/chunk/retrieval/answer checks."
    )
    parser.add_argument(
        "preset",
        nargs="?",
        choices=tuple(PRESET_DATASETS.keys()),
        help="Named evaluation preset. Omit this and pass --dataset for a custom file.",
    )
    parser.add_argument(
        "--dataset",
        help="Custom evaluation JSON file. Overrides preset if provided.",
    )
    parser.add_argument(
        "--layer",
        choices=("parse", "chunk", "retrieval", "facts", "answer", "all"),
        help="Layer to run. Defaults to the preset's recommended layer.",
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List available evaluation presets and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    if args.list:
        for name, (dataset, default_layer) in PRESET_DATASETS.items():
            print(f"{name:12} dataset={dataset} default_layer={default_layer}")
        return

    if not args.dataset and not args.preset:
        raise SystemExit("usage: python scripts/eval.py <preset> [--layer ...] or --dataset <file>")

    if args.dataset:
        dataset = args.dataset
        layer = args.layer or "all"
    else:
        dataset, default_layer = PRESET_DATASETS[args.preset]
        layer = args.layer or default_layer

    eval_layers_main(dataset, layer)


if __name__ == "__main__":
    main()
