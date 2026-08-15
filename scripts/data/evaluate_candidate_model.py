#!/usr/bin/env python3
"""scripts/data/evaluate_candidate_model.py

CLI wrapper around bonbon_data_pipeline.model_evaluation.evaluate_for_deployment
/ evaluate_and_record -- the literal "a model can become default only if it
passes all 7 criteria" gate, runnable from a shell/CI step rather than only
from Python.

Reads a JSON candidate file matching CandidateBenchmark's fields (produced
by scripts/data/benchmark_candidate_on_pi.py, or hand-authored for a
non-Pi-hosted capability like RAG). Exits 0 if the candidate is ALLOWED to
become the default model, exits 1 otherwise -- so a CI/deploy pipeline can
gate a promotion step on this script's exit code rather than parsing text.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bonbon_data_pipeline.model_evaluation import (  # noqa: E402
    CandidateBenchmark,
    evaluate_and_record,
    evaluate_for_deployment,
)
from bonbon_field_learning.model_evaluation_tracker import ModelEvaluationTracker  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("candidate_json", type=Path, help="Path to a CandidateBenchmark-shaped JSON file")
    parser.add_argument(
        "--tracker-path", type=Path,
        default=Path("project-status/field_learning/model_evaluation.json"),
        help="Same file bonbon_operator_api's /models/evaluation endpoint reads via ModelEvaluationTracker",
    )
    parser.add_argument(
        "--record", action="store_true",
        help="If the gate passes, record it as the new regression baseline (default: dry-run, report only)",
    )
    args = parser.parse_args()

    if not args.candidate_json.is_file():
        print(f"BLOCKED: candidate file not found: {args.candidate_json}", file=sys.stderr)
        return 1

    data = json.loads(args.candidate_json.read_text(encoding="utf-8"))
    try:
        candidate = CandidateBenchmark(**data)
    except TypeError as exc:
        print(f"BLOCKED: candidate JSON does not match CandidateBenchmark's fields: {exc}", file=sys.stderr)
        return 1

    tracker = ModelEvaluationTracker(args.tracker_path)
    result = evaluate_and_record(candidate, tracker) if args.record else evaluate_for_deployment(candidate, tracker)

    print(json.dumps(result.to_dict(), indent=2))
    if not result.allowed:
        print("\nBLOCKED -- failing/unverified criteria:", file=sys.stderr)
        for reason in result.failing_reasons():
            print(f"  - {reason}", file=sys.stderr)
    return 0 if result.allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())
