"""bonbon_edge_ai_runtime.runtime_selector -- re-exports
bonbon_ai_model_registry.model_runtime_selector.ModelRuntimeSelector
unchanged. Per docs/DUPLICATE_PIPELINE_AUDIT.md, that selector already
does real availability checking (pip/ollama/hailo/external_api) across
all capabilities including the 3 this package adds -- there is nothing
for a second runtime_selector.py to do that isn't already done. This
module exists so bonbon_edge_ai_runtime's own callers (task_router,
dashboard_publisher) can `from bonbon_edge_ai_runtime.runtime_selector
import ModelRuntimeSelector` without needing to know the selector
actually lives in a different package -- a namespace convenience, not a
reimplementation.
"""

from __future__ import annotations

from bonbon_ai_model_registry.model_fallback_policy import FallbackDecision  # noqa: F401 -- re-exported
from bonbon_ai_model_registry.model_runtime_selector import (  # noqa: F401 -- re-exported
    ModelRuntimeSelector,
    RuntimeStatus,
)
