"""ModelEntry / ModelRegistry — the single source of truth for which model
backs which AI capability, loaded from config/models/*.yaml. Every other
module in this package (license checker, downloader, runtime selector,
benchmark runner, health monitor, dashboard publisher) reads from a
ModelRegistry rather than hardcoding a model name anywhere.

Not a duplicate of bonbon_ai_runtime.RuntimeSelector: that package
selects hailo/cpu/mock for one already-chosen vision model at inference
time. This registry answers the earlier question -- which model, from
which provider, under which license, is even a candidate for a given
capability -- across every AI capability BonBon has, not just vision.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml

CommercialAllowed = Literal["true", "false", "unknown"]
DownloadType = Literal["ollama", "pip", "git", "wget", "manual", "api", "unavailable"]
HardwareTarget = Literal["pi_cpu", "hailo_8", "hailo_10h", "oak_d", "external_api", "mock"]

# The 16 capabilities this task's brief names, kept as one canonical list
# so every config file / test can validate against it rather than typo a
# capability string independently.
CAPABILITIES = (
    "local_llm",
    "asr",
    "tts",
    "wake_word",
    "vad",
    "translation",
    "object_detection",
    "person_detection",
    "face_recognition",
    "face_emotion",
    "voice_emotion",
    "speaker_diarization",
    "gesture_recognition",
    "pose_estimation",
    "local_rag",
    "hospital_faq",
    # Added for bonbon_edge_ai_runtime (Edge AI Runtime brief, Phase 3):
    # capabilities that brief names but the original 16-function AI model
    # stack pass didn't need a registry entry for. Added here rather than
    # in a second CAPABILITIES tuple so every ModelRegistry.validate()
    # call -- old and new callers alike -- recognizes them; see
    # docs/DUPLICATE_PIPELINE_AUDIT.md for why bonbon_edge_ai_runtime
    # extends this registry instead of building a second one.
    "human_state_fusion",
    "intent_classification",
    "assistant_guardrails",
)


@dataclass
class ModelEntry:
    model_id: str
    capability: str
    provider: str
    model_name: str
    version: str
    purpose: str
    license: str
    commercial_allowed: CommercialAllowed
    download_type: DownloadType
    download_command: str
    hardware_target: HardwareTarget
    runtime: str
    expected_ram_mb: int
    expected_storage_mb: int
    expected_latency_ms: int
    fallback_model_id: str | None
    dashboard_visible: bool = True
    enabled_by_default: bool = False
    languages: list[str] = field(default_factory=list)
    notes: str = ""
    # Not in the brief's minimum field list, but needed to make
    # model_runtime_selector's availability checks real rather than
    # guessed: the actual `import x` name for download_type="pip" entries
    # (e.g. model_name="faster-whisper", import_name="faster_whisper").
    # Empty string means "no generic checker possible, needs a bespoke
    # availability_checkers[model_id] callable" -- never silently assumed
    # available.
    import_name: str = ""
    # model_name is a human-readable DISPLAY string throughout this
    # registry (e.g. "DeepFace (Facenet512 backend)", "en_US-lessac-medium
    # (Piper)") -- never guaranteed to match an on-disk filename. Entries
    # whose runtime needs to build a real file path (e.g. TTSRouter
    # locating a downloaded Piper .onnx voice) must use asset_filename
    # instead, which is exactly the filename stem
    # scripts/ai_models/install_piper_tts.sh (or the equivalent download
    # command) actually writes to disk. Empty means "no separate on-disk
    # asset, or model_name already happens to be the real identifier"
    # (e.g. Ollama model tags like "qwen2.5:0.5b" are already both).
    asset_filename: str = ""

    @classmethod
    def from_dict(cls, model_id: str, data: dict[str, Any]) -> "ModelEntry":
        required = (
            "capability", "provider", "model_name", "version", "purpose", "license",
            "commercial_allowed", "download_type", "download_command", "hardware_target",
            "runtime", "expected_ram_mb", "expected_storage_mb", "expected_latency_ms",
        )
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"model entry {model_id!r} is missing required fields: {missing}")
        return cls(
            model_id=model_id,
            capability=data["capability"],
            provider=data["provider"],
            model_name=data["model_name"],
            version=data["version"],
            purpose=data["purpose"],
            license=data["license"],
            commercial_allowed=data["commercial_allowed"],
            download_type=data["download_type"],
            download_command=data["download_command"],
            hardware_target=data["hardware_target"],
            runtime=data["runtime"],
            expected_ram_mb=int(data["expected_ram_mb"]),
            expected_storage_mb=int(data["expected_storage_mb"]),
            expected_latency_ms=int(data["expected_latency_ms"]),
            fallback_model_id=data.get("fallback_model_id"),
            dashboard_visible=bool(data.get("dashboard_visible", True)),
            enabled_by_default=bool(data.get("enabled_by_default", False)),
            languages=list(data.get("languages", [])),
            notes=str(data.get("notes", "")),
            import_name=str(data.get("import_name", "")),
            asset_filename=str(data.get("asset_filename", "")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "modelId": self.model_id,
            "capability": self.capability,
            "provider": self.provider,
            "modelName": self.model_name,
            "version": self.version,
            "purpose": self.purpose,
            "license": self.license,
            "commercialAllowed": self.commercial_allowed,
            "downloadType": self.download_type,
            "downloadCommand": self.download_command,
            "hardwareTarget": self.hardware_target,
            "runtime": self.runtime,
            "expectedRamMb": self.expected_ram_mb,
            "expectedStorageMb": self.expected_storage_mb,
            "expectedLatencyMs": self.expected_latency_ms,
            "fallbackModelId": self.fallback_model_id,
            "dashboardVisible": self.dashboard_visible,
            "enabledByDefault": self.enabled_by_default,
            "languages": self.languages,
            "notes": self.notes,
            "importName": self.import_name,
            "assetFilename": self.asset_filename,
        }


class ModelRegistry:
    """Loads and indexes config/models/model_registry.yaml. A profile
    overlay (pi_ai_hat_plus_2_profile.yaml etc) may override
    `enabled_by_default` per model_id without duplicating the whole
    entry -- see model_runtime_selector.py for how a profile is applied."""

    def __init__(self, entries: dict[str, ModelEntry]) -> None:
        self._entries = entries

    @classmethod
    def load(cls, registry_path: str | Path) -> "ModelRegistry":
        path = Path(registry_path)
        if not path.exists():
            raise FileNotFoundError(f"model registry config not found: {path}")
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        models = raw.get("models", {})
        entries = {model_id: ModelEntry.from_dict(model_id, data) for model_id, data in models.items()}
        return cls(entries)

    def get(self, model_id: str) -> ModelEntry | None:
        return self._entries.get(model_id)

    def all(self) -> list[ModelEntry]:
        return list(self._entries.values())

    def by_capability(self, capability: str) -> list[ModelEntry]:
        return [e for e in self._entries.values() if e.capability == capability]

    def default_for_capability(self, capability: str) -> ModelEntry | None:
        """The enabled-by-default entry for a capability, if any. Ties are
        resolved by declaration order in the YAML (first wins) -- a
        capability should not declare two defaults; that's a config bug
        the license checker's own validation step surfaces, not silently
        picked-first here without comment."""
        candidates = [e for e in self.by_capability(capability) if e.enabled_by_default]
        return candidates[0] if candidates else None

    def fallback_chain(self, model_id: str) -> list[ModelEntry]:
        """Walks fallback_model_id from a starting entry to its terminal
        fallback, guarding against a cyclic config (would otherwise loop
        forever) by capping at len(entries)+1 hops."""
        chain: list[ModelEntry] = []
        seen: set[str] = set()
        current = self.get(model_id)
        limit = len(self._entries) + 1
        while current is not None and current.model_id not in seen and len(chain) < limit:
            chain.append(current)
            seen.add(current.model_id)
            current = self.get(current.fallback_model_id) if current.fallback_model_id else None
        return chain

    def apply_profile_overrides(self, overrides: dict[str, bool]) -> "ModelRegistry":
        """Returns a NEW registry with `enabled_by_default` overridden per
        model_id from a hardware profile (e.g. pi_cpu_fallback_profile.yaml
        disabling every hailo_8/hailo_10h entry). Never mutates the
        original -- callers that need the base registry's own opinion
        (e.g. the license checker validating the authored config) must
        still see the unmodified version."""
        new_entries = copy.deepcopy(self._entries)
        for model_id, enabled in overrides.items():
            if model_id in new_entries:
                new_entries[model_id].enabled_by_default = enabled
        return ModelRegistry(new_entries)

    def validate(self) -> list[str]:
        """Returns a list of human-readable problems (empty = clean).
        Never raises -- callers decide whether validation failures are
        fatal (e.g. the license checker treats an unresolvable fallback
        chain as license-blocking, since a model with no safe fallback
        must never be auto-enabled)."""
        problems: list[str] = []
        seen_defaults: dict[str, str] = {}
        for entry in self._entries.values():
            if entry.capability not in CAPABILITIES:
                problems.append(f"{entry.model_id}: unknown capability {entry.capability!r}")
            if entry.fallback_model_id and entry.fallback_model_id not in self._entries:
                problems.append(f"{entry.model_id}: fallback_model_id {entry.fallback_model_id!r} does not exist")
            if entry.enabled_by_default:
                prior = seen_defaults.get(entry.capability)
                if prior:
                    problems.append(
                        f"capability {entry.capability!r} has two enabled_by_default entries: {prior!r} and {entry.model_id!r}"
                    )
                seen_defaults[entry.capability] = entry.model_id
        return problems
