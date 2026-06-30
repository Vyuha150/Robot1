"""bonbon_ai_runtime — pluggable vision-model inference runtimes.

Public API: VisionModelRuntimeInterface, RuntimeKind, RuntimeStatus,
InferenceOutput, RuntimeHealth, BenchmarkResult, the four runtimes
(Mock/CPUONNX/TensorRT/Hailo), HailoDeviceDetector, ModelCompatibilityChecker,
ModelRuntimeHealthMonitor, InferenceMetricsCollector, and the
RuntimeSelector/RuntimeSpec/RuntimeMode/SelectionResult.
"""

from bonbon_ai_runtime.cpu_onnx_runtime import CPUONNXRuntime
from bonbon_ai_runtime.hailo_device_detector import HailoDetection, HailoDeviceDetector
from bonbon_ai_runtime.hailo_runtime import HailoRuntime
from bonbon_ai_runtime.health_monitor import ModelRuntimeHealthMonitor
from bonbon_ai_runtime.interface import (
    AvailabilityResult,
    BenchmarkResult,
    InferenceOutput,
    RuntimeHealth,
    RuntimeKind,
    RuntimeStatus,
    VisionModelRuntimeInterface,
)
from bonbon_ai_runtime.metrics_collector import InferenceMetricsCollector
from bonbon_ai_runtime.mock_runtime import MockRuntime
from bonbon_ai_runtime.model_compatibility import CompatibilityResult, ModelCompatibilityChecker
from bonbon_ai_runtime.runtime_selector import (
    RuntimeMode,
    RuntimeSelector,
    RuntimeSpec,
    SelectionResult,
)
from bonbon_ai_runtime.tensorrt_runtime import TensorRTRuntime

__all__ = [
    "VisionModelRuntimeInterface",
    "RuntimeKind",
    "RuntimeStatus",
    "InferenceOutput",
    "RuntimeHealth",
    "BenchmarkResult",
    "AvailabilityResult",
    "MockRuntime",
    "CPUONNXRuntime",
    "TensorRTRuntime",
    "HailoRuntime",
    "HailoDeviceDetector",
    "HailoDetection",
    "ModelCompatibilityChecker",
    "CompatibilityResult",
    "ModelRuntimeHealthMonitor",
    "InferenceMetricsCollector",
    "RuntimeSelector",
    "RuntimeSpec",
    "RuntimeMode",
    "SelectionResult",
]
