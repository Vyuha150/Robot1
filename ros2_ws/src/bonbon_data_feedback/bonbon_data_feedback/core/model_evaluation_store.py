"""ModelEvaluationStore — records and compares model evaluation runs
(accuracy on a held-out sample) across versions, so "did v3 actually beat
v2" has a stored answer instead of a remembered one.
"""

from __future__ import annotations

from dataclasses import dataclass

from bonbon_data_feedback.core.feedback_store import FeedbackStore


@dataclass
class EvaluationComparison:
    model_name: str
    version_a: str
    version_b: str
    accuracy_a: float | None
    accuracy_b: float | None
    improved: bool | None  # None if either accuracy is missing


class ModelEvaluationStore:
    def __init__(self, store: FeedbackStore) -> None:
        self._store = store

    def record_evaluation(
        self,
        model_name: str,
        model_version: str,
        category: str,
        sample_count: int,
        accuracy: float | None,
        notes: str = "",
    ) -> str:
        return self._store.insert_model_evaluation(
            model_name, model_version, category, sample_count, accuracy, notes
        )

    def list_evaluations(self, model_name: str | None = None) -> list[dict]:
        return self._store.list_model_evaluations(model_name=model_name)

    def compare(self, model_name: str, version_a: str, version_b: str) -> EvaluationComparison:
        evals = self._store.list_model_evaluations(model_name=model_name)
        acc_a = next((e["accuracy"] for e in evals if e["model_version"] == version_a), None)
        acc_b = next((e["accuracy"] for e in evals if e["model_version"] == version_b), None)
        improved = (acc_b > acc_a) if (acc_a is not None and acc_b is not None) else None
        return EvaluationComparison(model_name, version_a, version_b, acc_a, acc_b, improved)
