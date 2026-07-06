"""RuntimeSelector — choose the vision inference runtime from config +
detected hardware + model availability, with a logged, inspectable fallback
chain.

`auto` mode walks `runtime_priority` (e.g. [hailo, cpu, mock]) and picks the
first runtime that is available, format-compatible with its configured
model, and loads successfully. Anything other than the first choice means
`fallback_active=True` with a reason — which the dashboard surfaces. If
nothing loads and `fail_open_to_degraded_mode` is set, the MockRuntime is
the guaranteed last resort so the vision node always has a live (degraded)
backend rather than crashing.

Explicit modes (`cpu`/`hailo`/`tensorrt`/`mock`) try only that runtime, then
fall open to mock if allowed.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

from bonbon_ai_runtime.cpu_onnx_runtime import CPUONNXRuntime
from bonbon_ai_runtime.hailo_runtime import HailoRuntime
from bonbon_ai_runtime.interface import RuntimeKind, VisionModelRuntimeInterface
from bonbon_ai_runtime.mock_runtime import MockRuntime
from bonbon_ai_runtime.model_compatibility import ModelCompatibilityChecker
from bonbon_ai_runtime.tensorrt_runtime import TensorRTRuntime


class RuntimeMode(str, Enum):
    AUTO = "auto"
    CPU = "cpu"
    HAILO = "hailo"
    TENSORRT = "tensorrt"
    MOCK = "mock"


_MODE_TO_KIND = {
    RuntimeMode.CPU: RuntimeKind.CPU,
    RuntimeMode.HAILO: RuntimeKind.HAILO,
    RuntimeMode.TENSORRT: RuntimeKind.TENSORRT,
    RuntimeMode.MOCK: RuntimeKind.MOCK,
}

_DEFAULT_PRIORITY = [RuntimeKind.HAILO, RuntimeKind.CPU, RuntimeKind.MOCK]


@dataclass
class RuntimeSpec:
    mode: RuntimeMode = RuntimeMode.AUTO
    runtime_priority: list[RuntimeKind] = field(default_factory=lambda: list(_DEFAULT_PRIORITY))
    model_paths: dict[RuntimeKind, str] = field(default_factory=dict)
    fail_open_to_degraded_mode: bool = True


@dataclass
class AttemptRecord:
    kind: RuntimeKind
    available: bool
    compatible: bool
    loaded: bool
    reason: str


@dataclass
class SelectionResult:
    runtime: VisionModelRuntimeInterface
    selected_kind: RuntimeKind
    fallback_active: bool
    fallback_reason: str
    chain: list[AttemptRecord] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "selected_runtime": self.runtime.name,
            "selected_kind": self.selected_kind.value,
            "fallback_active": self.fallback_active,
            "fallback_reason": self.fallback_reason,
            "model_loaded": self.runtime.health().model_loaded,
            "chain": [
                {
                    "kind": a.kind.value,
                    "available": a.available,
                    "compatible": a.compatible,
                    "loaded": a.loaded,
                    "reason": a.reason,
                }
                for a in self.chain
            ],
        }


# kind -> runtime factory; injectable so tests can supply a Hailo runtime
# wired with a mocked detector/infer-factory.
RuntimeFactory = Callable[[RuntimeKind], VisionModelRuntimeInterface]


def _default_factory(kind: RuntimeKind) -> VisionModelRuntimeInterface:
    if kind == RuntimeKind.HAILO:
        return HailoRuntime()
    if kind == RuntimeKind.CPU:
        return CPUONNXRuntime()
    if kind == RuntimeKind.TENSORRT:
        return TensorRTRuntime()
    return MockRuntime()


class RuntimeSelector:
    def __init__(self, factory: RuntimeFactory | None = None) -> None:
        self._factory = factory or _default_factory

    def select(self, spec: RuntimeSpec) -> SelectionResult:
        chain: list[AttemptRecord] = []

        order = self._resolve_order(spec)
        preferred = order[0] if order else RuntimeKind.MOCK

        for kind in order:
            runtime = self._factory(kind)
            model_path = spec.model_paths.get(kind, "")
            avail = runtime.is_available()
            compat = ModelCompatibilityChecker.check(kind, model_path)
            loaded = False
            reason = avail.reason

            if avail.available and compat.compatible:
                loaded = runtime.load_model(model_path)
                reason = "loaded" if loaded else "available+compatible but load failed"
            elif not avail.available:
                reason = f"unavailable: {avail.reason}"
            else:
                reason = f"model incompatible: {compat.reason}"

            chain.append(AttemptRecord(kind, avail.available, compat.compatible, loaded, reason))

            if loaded:
                fallback = kind != preferred
                fb_reason = (
                    ""
                    if not fallback
                    else f"preferred '{preferred.value}' unavailable; using '{kind.value}'"
                )
                return SelectionResult(runtime, kind, fallback, fb_reason, chain)

        # Nothing in the order loaded. Fall open to mock if allowed.
        if spec.fail_open_to_degraded_mode:
            mock = self._factory(RuntimeKind.MOCK)
            mock.load_model("")
            chain.append(
                AttemptRecord(RuntimeKind.MOCK, True, True, True, "fail-open degraded fallback")
            )
            return SelectionResult(
                mock,
                RuntimeKind.MOCK,
                fallback_active=True,
                fallback_reason="all configured runtimes unavailable — degraded mock fallback",
                chain=chain,
            )

        # fail-closed: still return the (unloaded) preferred runtime so the
        # caller can inspect health; selection is marked as a failed fallback.
        runtime = self._factory(preferred)
        return SelectionResult(
            runtime,
            preferred,
            fallback_active=True,
            fallback_reason="no runtime could load and fail-open is disabled",
            chain=chain,
        )

    def _resolve_order(self, spec: RuntimeSpec) -> list[RuntimeKind]:
        if spec.mode == RuntimeMode.AUTO:
            order = list(spec.runtime_priority) or list(_DEFAULT_PRIORITY)
            # Mock is always the implicit final safety net in auto mode.
            if RuntimeKind.MOCK not in order:
                order = order + [RuntimeKind.MOCK]
            return order
        # Explicit mode: just that one kind.
        return [_MODE_TO_KIND[spec.mode]]
