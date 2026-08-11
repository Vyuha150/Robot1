"""bonbon_edge_ai_runtime.fallback_manager -- re-exports
bonbon_ai_model_registry.model_fallback_policy.FallbackPolicy unchanged.
Per docs/DUPLICATE_PIPELINE_AUDIT.md: FallbackPolicy already walks a
model's fallback_model_id chain against real availability results and
reports `degraded=True` honestly when a chain is exhausted -- exactly
what "Phase 2: fallback_manager.py" asks for. Nothing to reimplement.
"""

from __future__ import annotations

from bonbon_ai_model_registry.model_fallback_policy import (  # noqa: F401 -- re-exported
    FallbackDecision,
    FallbackPolicy,
)
