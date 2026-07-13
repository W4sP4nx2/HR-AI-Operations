"""Print the resource-bounded naive-baseline evaluation report."""

from __future__ import annotations

import argparse
import json

from models.baseline_evaluation import evaluate_all


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--compact", action="store_true", help="emit one-line JSON")
    args = parser.parse_args()
    print(json.dumps(evaluate_all(), indent=None if args.compact else 2, sort_keys=True))


if __name__ == "__main__":
    main()
