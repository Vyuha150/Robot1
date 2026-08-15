"""TrainingManifest -- per-capability record of what BonBon trains, on
which datasets, on which machine, evaluated against which threshold, with
which rollback plan. Backs config/data/training_targets.yaml and
docs/TRAINING_AND_FINE_TUNING_PLAN.md; the doc explains the policy in
prose, this module makes it a machine-checkable structure the dashboard
and evaluate_candidate_model.py can both read.

Enforces rule 7 structurally: `validate_against_registry` fails any target
whose training_machine names a Pi/edge board -- fine-tuning must happen on
a workstation/GPU, never on the robot's own boards.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from bonbon_data_pipeline.dataset_license_checker import DatasetLicenseChecker
from bonbon_data_pipeline.dataset_registry import DatasetRegistry

# Substrings that flag a training_machine value as an on-robot edge board --
# rule 7 forbids ever declaring one of these as where fine-tuning happens.
_FORBIDDEN_TRAINING_MACHINE_SUBSTRINGS = ("raspberry_pi", "pi_1", "pi_2", "pi_3", "hailo", "edge_board")


@dataclass
class TrainingTarget:
    capability: str
    baseline_model: str
    dataset_ids: list[str]
    training_machine: str
    training_method: str
    evaluation_metric: str
    acceptance_threshold: float
    edge_export_format: str
    rollback_plan: str

    @classmethod
    def from_dict(cls, capability: str, data: dict[str, Any]) -> "TrainingTarget":
        required = (
            "baseline_model", "dataset_ids", "training_machine", "training_method",
            "evaluation_metric", "acceptance_threshold", "edge_export_format", "rollback_plan",
        )
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"training target {capability!r} is missing required fields: {missing}")
        return cls(
            capability=capability,
            baseline_model=data["baseline_model"],
            dataset_ids=list(data["dataset_ids"]),
            training_machine=data["training_machine"],
            training_method=data["training_method"],
            evaluation_metric=data["evaluation_metric"],
            acceptance_threshold=float(data["acceptance_threshold"]),
            edge_export_format=data["edge_export_format"],
            rollback_plan=data["rollback_plan"],
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "baselineModel": self.baseline_model,
            "datasetIds": self.dataset_ids,
            "trainingMachine": self.training_machine,
            "trainingMethod": self.training_method,
            "evaluationMetric": self.evaluation_metric,
            "acceptanceThreshold": self.acceptance_threshold,
            "edgeExportFormat": self.edge_export_format,
            "rollbackPlan": self.rollback_plan,
        }


class TrainingManifest:
    def __init__(self, targets: dict[str, TrainingTarget]) -> None:
        self._targets = targets

    @classmethod
    def load(cls, path: str | Path) -> "TrainingManifest":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"training targets config not found: {p}")
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        targets = raw.get("targets", {})
        return cls({cap: TrainingTarget.from_dict(cap, data) for cap, data in targets.items()})

    def get(self, capability: str) -> TrainingTarget | None:
        return self._targets.get(capability)

    def all(self) -> list[TrainingTarget]:
        return list(self._targets.values())

    def validate_against_registry(
        self, registry: DatasetRegistry, *, production_training: bool = True
    ) -> list[str]:
        """Cross-checks every target's dataset_ids actually exist in the
        dataset registry and are license-cleared for training use. Returns
        human-readable problems (empty = clean); never raises."""
        problems: list[str] = []
        checker = DatasetLicenseChecker()
        for target in self._targets.values():
            lowered_machine = target.training_machine.lower()
            if any(bad in lowered_machine for bad in _FORBIDDEN_TRAINING_MACHINE_SUBSTRINGS):
                problems.append(
                    f"{target.capability}: training_machine={target.training_machine!r} names an "
                    "on-robot edge board -- rule 7 requires workstation/GPU fine-tuning"
                )
            if not target.dataset_ids:
                problems.append(f"{target.capability}: no dataset_ids declared")
            for dataset_id in target.dataset_ids:
                entry = registry.get(dataset_id)
                if entry is None:
                    problems.append(f"{target.capability}: dataset_id {dataset_id!r} not found in dataset registry")
                    continue
                decision = checker.check(entry, production_training=production_training)
                if not decision.allowed:
                    problems.append(
                        f"{target.capability}: dataset {dataset_id!r} is not usable for training -- {decision.reason}"
                    )
        return problems

    def resolve_datasets(self, capability: str, registry: DatasetRegistry) -> list:
        target = self.get(capability)
        if target is None:
            return []
        return [e for e in (registry.get(ds_id) for ds_id in target.dataset_ids) if e is not None]
