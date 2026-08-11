"""bonbon_edge_ai_runtime.model_registry -- the Edge AI Runtime brief's
Phase 2/3 "model registry", implemented as a MERGE over the real,
existing bonbon_ai_model_registry rather than a second, competing
registry. See docs/DUPLICATE_PIPELINE_AUDIT.md: building a from-scratch
ModelEntry/ModelRegistry here would duplicate 39 already-registered,
already-tested entries covering 16 capabilities. This module adds only
the 3 capabilities (human_state_fusion, intent_classification,
assistant_guardrails) config/models/model_registry.yaml never needed to
cover, defined in config/edge_ai/model_registry.yaml, and re-exports the
real ModelEntry/ModelRegistry classes unchanged so every other module in
this package (and every existing caller of bonbon_ai_model_registry)
shares one data model, not two.
"""

from __future__ import annotations

from pathlib import Path

from bonbon_ai_model_registry.model_registry import (  # noqa: F401 -- re-exported
    CAPABILITIES,
    ModelEntry,
    ModelRegistry,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]
BASE_REGISTRY_PATH = _REPO_ROOT / "config" / "models" / "model_registry.yaml"
EDGE_REGISTRY_PATH = _REPO_ROOT / "config" / "edge_ai" / "model_registry.yaml"


def load_merged(
    base_path: str | Path = BASE_REGISTRY_PATH,
    edge_path: str | Path = EDGE_REGISTRY_PATH,
) -> ModelRegistry:
    """Loads both registries and returns one merged ModelRegistry
    covering all 19 capabilities (16 original + 3 edge-ai-only). A
    model_id collision (should never happen -- the two files are
    namespaced by convention) lets the edge_ai entry win, since it's the
    more specific/recent config; validate() should be called by the
    caller immediately after to catch that rather than silently proceed."""
    base = ModelRegistry.load(base_path)
    edge = ModelRegistry.load(edge_path)
    merged: dict[str, ModelEntry] = {e.model_id: e for e in base.all()}
    merged.update({e.model_id: e for e in edge.all()})
    return ModelRegistry(merged)
