#!/usr/bin/env python3
"""Compare offline predictions to real measurements without touching a printer.

Inputs are JSON objects. Prediction keys use the documented schema in the
Printer Lab API; actual values use the matching Printer Lab measurement names.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "backend"))
from services.prediction_analysis import analyze, markdown, validate_predictions, finite_nonnegative  # noqa: E402


def read_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path}: invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predicted", type=Path, required=True)
    parser.add_argument("--actual", type=Path, required=True)
    parser.add_argument("--slicer-estimate-seconds", type=float)
    parser.add_argument("--output-json", type=Path, required=True)
    parser.add_argument("--output-markdown", type=Path, required=True)
    args = parser.parse_args()
    try:
        predicted = validate_predictions(read_object(args.predicted))
        actual_raw = read_object(args.actual)
        actual = {key: finite_nonnegative(value, key) for key, value in actual_raw.items()}
        estimate = (finite_nonnegative(args.slicer_estimate_seconds, "slicer_estimate_seconds")
                    if args.slicer_estimate_seconds is not None else None)
        report = analyze(predicted, actual, estimate)
    except ValueError as exc:
        raise SystemExit(f"Input error: {exc}")
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.output_markdown.write_text(markdown(report), encoding="utf-8")
    print(f"Wrote analysis: {args.output_json} and {args.output_markdown}")
    print("No printer settings were changed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
