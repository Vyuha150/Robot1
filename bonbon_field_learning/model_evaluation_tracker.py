"""Records model evaluation runs against the regression scenario catalog
and decides whether a deployment is allowed -- the literal "blocks
deployment if regression worsens" requirement.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EvaluationRun:
    model_version: str
    dataset_version: str
    regression_pass_rate: float  # 0.0-1.0
    total_regression_scenarios: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, object]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> EvaluationRun:
        return cls(
            model_version=str(data["model_version"]),
            dataset_version=str(data["dataset_version"]),
            regression_pass_rate=float(data["regression_pass_rate"]),
            total_regression_scenarios=int(data["total_regression_scenarios"]),
            timestamp=float(data["timestamp"]),
        )


# A new model may not regress the pass rate by more than this much versus
# the last recorded evaluation -- catches "fixed one thing, broke another".
_MAX_ALLOWED_REGRESSION = 0.0


class ModelEvaluationTracker:
    def __init__(self, path: Path | str) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _runs(self) -> list[EvaluationRun]:
        if not self._path.exists():
            return []
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)
        return [EvaluationRun.from_dict(d) for d in data.get("runs", [])]

    def _write(self, runs: list[EvaluationRun]) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump({"runs": [r.to_dict() for r in runs]}, f, indent=2)

    def record(self, run: EvaluationRun) -> None:
        runs = self._runs()
        runs.append(run)
        self._write(runs)

    def latest(self) -> EvaluationRun | None:
        runs = self._runs()
        return runs[-1] if runs else None

    def history(self) -> list[EvaluationRun]:
        return self._runs()

    def deployment_allowed(self, candidate: EvaluationRun) -> tuple[bool, str]:
        """Compares `candidate` against the most recent recorded run (not
        yet appended). Does NOT record `candidate` -- callers record it
        themselves once a deployment decision is made, so a rejected
        candidate's score is still visible for debugging without being
        treated as the new baseline."""
        previous = self.latest()
        if previous is None:
            return True, "no prior evaluation to compare against"

        delta = candidate.regression_pass_rate - previous.regression_pass_rate
        if delta < -_MAX_ALLOWED_REGRESSION:
            return False, (
                f"regression pass rate dropped {previous.regression_pass_rate:.1%} -> "
                f"{candidate.regression_pass_rate:.1%} (model {candidate.model_version} vs "
                f"{previous.model_version}); deployment BLOCKED"
            )
        return (
            True,
            f"regression pass rate {candidate.regression_pass_rate:.1%} (no regression vs previous)",
        )
