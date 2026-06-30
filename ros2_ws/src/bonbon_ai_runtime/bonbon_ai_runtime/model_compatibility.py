"""ModelCompatibilityChecker — which model file formats each runtime can
actually load, and whether the configured file for a runtime exists.

This is pure path/extension logic (no SDK calls), so it answers "is this
model usable by this runtime" during selection without touching hardware.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from bonbon_ai_runtime.interface import RuntimeKind

# Model file extensions each runtime can load.
_RUNTIME_EXTENSIONS: dict[RuntimeKind, frozenset[str]] = {
    RuntimeKind.HAILO: frozenset({".hef"}),
    RuntimeKind.CPU: frozenset({".onnx"}),
    RuntimeKind.TENSORRT: frozenset({".engine", ".plan", ".trt"}),
    RuntimeKind.MOCK: frozenset({"", ".onnx", ".hef", ".engine", ".pt"}),  # accepts anything
}


@dataclass
class CompatibilityResult:
    compatible: bool
    reason: str = ""
    model_path: str = ""
    model_exists: bool = False


class ModelCompatibilityChecker:
    @staticmethod
    def extensions_for(kind: RuntimeKind) -> frozenset[str]:
        return _RUNTIME_EXTENSIONS.get(kind, frozenset())

    @staticmethod
    def is_format_compatible(kind: RuntimeKind, model_path: str) -> bool:
        if kind == RuntimeKind.MOCK:
            return True
        ext = Path(model_path).suffix.lower()
        return ext in _RUNTIME_EXTENSIONS.get(kind, frozenset())

    @classmethod
    def check(cls, kind: RuntimeKind, model_path: str) -> CompatibilityResult:
        """Format-compatible AND (for non-mock) the file exists on disk."""
        if kind == RuntimeKind.MOCK:
            return CompatibilityResult(True, "mock accepts any model", model_path, True)
        if not model_path:
            return CompatibilityResult(
                False, f"no model path configured for {kind.value}", model_path, False
            )
        if not cls.is_format_compatible(kind, model_path):
            exts = ", ".join(sorted(cls.extensions_for(kind))) or "(none)"
            return CompatibilityResult(
                False,
                f"{kind.value} cannot load '{Path(model_path).suffix}' — needs one of: {exts}",
                model_path,
                Path(model_path).is_file(),
            )
        exists = Path(model_path).is_file()
        if not exists:
            return CompatibilityResult(
                False, f"model file not found: {model_path}", model_path, False
            )
        return CompatibilityResult(True, "compatible", model_path, True)
