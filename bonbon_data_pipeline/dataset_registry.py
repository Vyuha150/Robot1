"""DatasetEntry / DatasetRegistry -- the single source of truth for which
SOURCE TRAINING DATASET (public corpus, hospital-collected sample set, or
synthetic set) is a candidate for which capability, under which license.

Deliberately distinct from bonbon_ai_model_registry.ModelRegistry: that
registry tracks deployed MODEL ARTIFACTS (a specific ONNX/HEF/GGUF file and
its runtime). This registry answers the earlier question -- which raw
DATA was this model trained/fine-tuned/evaluated on, and was BonBon ever
allowed to use it -- across every AI capability, not just the ones with a
model already deployed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import yaml

CommercialAllowed = Literal["true", "false", "unknown"]
DatasetStatus = Literal["APPROVED", "NEEDS_REVIEW", "BLOCKED"]

# Kept as one canonical tuple (mirrors bonbon_ai_model_registry.CAPABILITIES)
# so a typo'd capability string in the YAML is a validate() error, not a
# silently-ignored dataset entry.
CAPABILITIES = (
    "asr",
    "tts",
    "object_detection",
    "person_detection",
    "gesture_recognition",
    "face_recognition",
    "face_emotion",
    "voice_emotion",
    "navigation",
    "hospital_knowledge_rag",
)

# Free-text but validated against this list -- "none" is the only value
# that means a dataset may ever be marked download_allowed=true without a
# privacy_guard review; anything else requires privacy_guard.py's explicit
# sign-off before download_allowed can be true (enforced in
# dataset_license_checker.py, not just documented here).
PRIVACY_RISK_LEVELS = (
    "none",  # e.g. synthetic data, landmark coordinates, text-only FAQ tables
    "low",  # e.g. anonymized/aggregated statistics
    "contains_raw_audio",
    "contains_raw_face_images",
    "contains_raw_video",
)


@dataclass
class DatasetEntry:
    dataset_id: str
    name: str
    source_url: str
    capability: str
    domain: str  # the brief's "language/object/domain" field -- e.g. "hindi", "hospital_corridor_objects"
    license: str
    commercial_allowed: CommercialAllowed
    privacy_risk: str
    download_allowed: bool
    intended_use: str
    prohibited_use: str
    preprocessing_needed: str
    target_model: str
    evaluation_metric: str
    edge_export_format: str
    status: DatasetStatus
    notes: str = ""

    @classmethod
    def from_dict(cls, dataset_id: str, data: dict[str, Any]) -> "DatasetEntry":
        required = (
            "name", "source_url", "capability", "domain", "license", "commercial_allowed",
            "privacy_risk", "download_allowed", "intended_use", "prohibited_use",
            "preprocessing_needed", "target_model", "evaluation_metric", "edge_export_format",
            "status",
        )
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"dataset entry {dataset_id!r} is missing required fields: {missing}")
        return cls(
            dataset_id=dataset_id,
            name=data["name"],
            source_url=data["source_url"],
            capability=data["capability"],
            domain=data["domain"],
            license=data["license"],
            commercial_allowed=data["commercial_allowed"],
            privacy_risk=data["privacy_risk"],
            download_allowed=bool(data["download_allowed"]),
            intended_use=data["intended_use"],
            prohibited_use=data["prohibited_use"],
            preprocessing_needed=data["preprocessing_needed"],
            target_model=data["target_model"],
            evaluation_metric=data["evaluation_metric"],
            edge_export_format=data["edge_export_format"],
            status=data["status"],
            notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "datasetId": self.dataset_id,
            "name": self.name,
            "sourceUrl": self.source_url,
            "capability": self.capability,
            "domain": self.domain,
            "license": self.license,
            "commercialAllowed": self.commercial_allowed,
            "privacyRisk": self.privacy_risk,
            "downloadAllowed": self.download_allowed,
            "intendedUse": self.intended_use,
            "prohibitedUse": self.prohibited_use,
            "preprocessingNeeded": self.preprocessing_needed,
            "targetModel": self.target_model,
            "evaluationMetric": self.evaluation_metric,
            "edgeExportFormat": self.edge_export_format,
            "status": self.status,
            "notes": self.notes,
        }


class DatasetRegistry:
    def __init__(self, entries: dict[str, DatasetEntry]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, registry_path: str | Path) -> "DatasetRegistry":
        path = Path(registry_path)
        if not path.exists():
            raise FileNotFoundError(f"dataset registry config not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        datasets = raw.get("datasets", {})
        entries = {ds_id: DatasetEntry.from_dict(ds_id, data) for ds_id, data in datasets.items()}
        return cls(entries)

    def get(self, dataset_id: str) -> DatasetEntry | None:
        return self._entries.get(dataset_id)

    def all(self) -> list[DatasetEntry]:
        return list(self._entries.values())

    def by_capability(self, capability: str) -> list[DatasetEntry]:
        return [e for e in self._entries.values() if e.capability == capability]

    def by_status(self, status: DatasetStatus) -> list[DatasetEntry]:
        return [e for e in self._entries.values() if e.status == status]

    def validate(self) -> list[str]:
        """Returns human-readable problems (empty = clean). Never raises --
        callers (the license checker, the dashboard) decide how to react."""
        problems: list[str] = []
        for entry in self._entries.values():
            if entry.capability not in CAPABILITIES:
                problems.append(f"{entry.dataset_id}: unknown capability {entry.capability!r}")
            if entry.privacy_risk not in PRIVACY_RISK_LEVELS:
                problems.append(f"{entry.dataset_id}: unknown privacy_risk {entry.privacy_risk!r}")
            if entry.status == "BLOCKED" and entry.download_allowed:
                problems.append(f"{entry.dataset_id}: status is BLOCKED but download_allowed=true")
            if entry.license.strip().lower() in ("", "unknown") and entry.status == "APPROVED":
                problems.append(
                    f"{entry.dataset_id}: license is unknown/empty but status is APPROVED "
                    "(rule 2 -- every dataset must have a checked license before approval)"
                )
        return problems
