"""Edge export policy + edge deployment status tracker (Phase 6/8).

Two responsibilities, kept in one module because they're two sides of the
same question ("what is actually running on the Pi right now, and how did
it get there"):

  1. ExportTargetRegistry -- given a capability, which export format is
     required (Hailo HEF for vision where possible, ONNX for CPU fallback,
     TFLite/ONNX for small classifiers, GGUF/Ollama for LLM experiments,
     SQLite/vector index for RAG, cached WAV/PCM for TTS phrases). Reads
     config/data/model_export_targets.yaml.

  2. EdgeDeploymentTracker -- a JSON-file-backed record of which model
     version is currently ACTIVE vs FALLBACK per capability, mirroring
     bonbon_field_learning.dataset_version_manager's storage pattern. This
     is the real data source for the dashboard's "Edge Deployment Status"
     section (active model / fallback model / model version / rollback
     available) -- not derived from bonbon_ai_model_registry's static
     config (which says what COULD run), but from what a real export/
     deploy action actually recorded as running.

Neither module runs an export itself -- see scripts/data/ for the actual
Hailo/ONNX/TFLite export commands this registry's `export_format` field
tells a caller to run.
"""

from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

ExportFormat = Literal["hailo_hef", "onnx", "tflite", "gguf", "sqlite_vector", "wav_cache"]

_VALID_FORMATS = frozenset(("hailo_hef", "onnx", "tflite", "gguf", "sqlite_vector", "wav_cache"))


@dataclass(frozen=True)
class ExportTarget:
    capability: str
    export_format: str
    hardware_target: str
    fallback_export_format: str | None
    notes: str = ""

    @classmethod
    def from_dict(cls, capability: str, data: dict[str, Any]) -> "ExportTarget":
        required = ("export_format", "hardware_target")
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"export target {capability!r} is missing required fields: {missing}")
        return cls(
            capability=capability,
            export_format=data["export_format"],
            hardware_target=data["hardware_target"],
            fallback_export_format=data.get("fallback_export_format"),
            notes=str(data.get("notes", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability": self.capability,
            "exportFormat": self.export_format,
            "hardwareTarget": self.hardware_target,
            "fallbackExportFormat": self.fallback_export_format,
            "notes": self.notes,
        }


class ExportTargetRegistry:
    def __init__(self, targets: dict[str, ExportTarget]) -> None:
        self._targets = targets

    @classmethod
    def load(cls, path: str | Path) -> "ExportTargetRegistry":
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"model export targets config not found: {p}")
        raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        targets = raw.get("targets", {})
        return cls({cap: ExportTarget.from_dict(cap, data) for cap, data in targets.items()})

    def get(self, capability: str) -> ExportTarget | None:
        return self._targets.get(capability)

    def all(self) -> list[ExportTarget]:
        return list(self._targets.values())

    def validate(self) -> list[str]:
        problems = []
        for target in self._targets.values():
            if target.export_format not in _VALID_FORMATS:
                problems.append(f"{target.capability}: unknown export_format {target.export_format!r}")
            if target.fallback_export_format and target.fallback_export_format not in _VALID_FORMATS:
                problems.append(
                    f"{target.capability}: unknown fallback_export_format {target.fallback_export_format!r}"
                )
        return problems


@dataclass
class EdgeDeploymentRecord:
    capability: str
    active_model_id: str
    active_model_version: str
    fallback_model_id: str | None
    fallback_model_version: str | None
    updated_at: float = field(default_factory=time.time)

    @property
    def rollback_available(self) -> bool:
        return self.fallback_model_id is not None

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["rollbackAvailable"] = self.rollback_available
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EdgeDeploymentRecord":
        return cls(
            capability=data["capability"],
            active_model_id=data["active_model_id"],
            active_model_version=data["active_model_version"],
            fallback_model_id=data.get("fallback_model_id"),
            fallback_model_version=data.get("fallback_model_version"),
            updated_at=float(data.get("updated_at", time.time())),
        )


class RollbackUnavailableError(RuntimeError):
    """Raised by rollback() when a capability has no recorded fallback --
    never silently no-ops, since a caller relying on rollback succeeding
    needs to know it didn't."""


class EdgeDeploymentTracker:
    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    def _all(self) -> dict[str, EdgeDeploymentRecord]:
        if not self._path.exists():
            return {}
        with open(self._path, encoding="utf-8") as f:
            data = json.load(f)
        return {cap: EdgeDeploymentRecord.from_dict(d) for cap, d in data.get("deployments", {}).items()}

    def _write(self, records: dict[str, EdgeDeploymentRecord]) -> None:
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump({"deployments": {cap: r.to_dict() for cap, r in records.items()}}, f, indent=2)

    def all(self) -> list[EdgeDeploymentRecord]:
        return list(self._all().values())

    def get(self, capability: str) -> EdgeDeploymentRecord | None:
        return self._all().get(capability)

    def set_active(
        self,
        capability: str,
        model_id: str,
        model_version: str,
        *,
        fallback_model_id: str | None = None,
        fallback_model_version: str | None = None,
    ) -> EdgeDeploymentRecord:
        """Promotes `model_id` to active. If no fallback is explicitly
        given and a deployment already exists for this capability, the
        PREVIOUS active model automatically becomes the new fallback --
        this is what makes rollback available by default after every
        normal promotion, not just when a caller remembers to set one."""
        records = self._all()
        previous = records.get(capability)
        if fallback_model_id is None and previous is not None:
            fallback_model_id = previous.active_model_id
            fallback_model_version = previous.active_model_version

        record = EdgeDeploymentRecord(
            capability=capability,
            active_model_id=model_id,
            active_model_version=model_version,
            fallback_model_id=fallback_model_id,
            fallback_model_version=fallback_model_version,
        )
        records[capability] = record
        self._write(records)
        return record

    def rollback(self, capability: str) -> EdgeDeploymentRecord:
        records = self._all()
        current = records.get(capability)
        if current is None or current.fallback_model_id is None:
            raise RollbackUnavailableError(f"no fallback recorded for capability {capability!r}")
        rolled_back = EdgeDeploymentRecord(
            capability=capability,
            active_model_id=current.fallback_model_id,
            active_model_version=current.fallback_model_version or "",
            fallback_model_id=current.active_model_id,
            fallback_model_version=current.active_model_version,
        )
        records[capability] = rolled_back
        self._write(records)
        return rolled_back
