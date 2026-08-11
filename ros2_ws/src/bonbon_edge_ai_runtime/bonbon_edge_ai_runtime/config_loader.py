"""bonbon_edge_ai_runtime.config_loader -- Edge AI Runtime brief Phase
2. Loads the 8 config/edge_ai/*.yaml files into one object. Several of
these files deliberately document/reference an existing, authoritative
config elsewhere (config/pi_efficiency_profile.yaml,
config/models/model_registry.yaml, config/runtime/model_runtime.yaml,
config/runtime/degraded_mode.yaml) rather than re-declaring those
values -- this loader does not resolve those cross-references itself;
each consuming module (inference_scheduler, model_registry,
accelerator_manager, degraded_mode_manager) reads its own authoritative
source directly, exactly as documented in this package's other modules.
"""

from __future__ import annotations

from pathlib import Path

import yaml

_REPO_ROOT = Path(__file__).resolve().parents[4]
CONFIG_DIR = _REPO_ROOT / "config" / "edge_ai"

_FILE_NAMES = (
    "model_registry",
    "task_routing",
    "runtime_profiles",
    "cache_policy",
    "resource_limits",
    "safety_separation",
    "degraded_modes",
    "three_pi_allocation",
)


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        raise FileNotFoundError(f"edge_ai config not found: {path}")
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


class EdgeAIConfig:
    """Read-only access to all 8 config/edge_ai/*.yaml files by name,
    e.g. `cfg['cache_policy']['rag_result_cache']['ttl_sec']`."""

    def __init__(self, values: dict[str, dict]) -> None:
        self._values = values

    @classmethod
    def load(cls, config_dir: str | Path | None = None) -> "EdgeAIConfig":
        base = Path(config_dir) if config_dir is not None else CONFIG_DIR
        values = {name: _load_yaml(base / f"{name}.yaml") for name in _FILE_NAMES}
        return cls(values)

    def __getitem__(self, name: str) -> dict:
        return self._values[name]

    def get(self, name: str, default: dict | None = None) -> dict:
        return self._values.get(name, default or {})

    def all_files_present(self) -> bool:
        """True if every one of the 8 files loaded non-empty content --
        used by the dashboard's production-readiness view, never
        assumed True without checking."""
        return all(bool(v) for v in self._values.values())

    def missing_files(self) -> list[str]:
        return [name for name, value in self._values.items() if not value]
