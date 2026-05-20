from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.eval_layers import main as eval_layers_main


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: python scripts/eval_rag.py <eval.json>")
    print("deprecated: use `python scripts/eval.py retrieval` or `python scripts/eval.py --dataset <file> --layer retrieval`", file=sys.stderr)
    eval_layers_main(sys.argv[1], "retrieval")
