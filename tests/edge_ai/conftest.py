"""Shared fixtures for tests/edge_ai/ -- Edge AI Runtime brief Phase 13.
Points sys.path at bonbon_edge_ai_runtime and every sibling colcon
package it imports (directly or lazily), matching the pattern in
tests/ai_models/conftest.py. These are real, checked-in packages and
config files -- no synthetic stand-ins.
"""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SRC = _REPO_ROOT / "ros2_ws" / "src"

for _extra in (
    _SRC / "bonbon_edge_ai_runtime",
    _SRC / "bonbon_ai_model_registry",
    _SRC / "bonbon_ai_runtime",
    _SRC / "bonbon_sarvam_adapter",
    _SRC / "bonbon_perception_efficiency",
    _SRC / "bonbon_llm",
    _SRC / "bonbon_safety",
):
    if str(_extra) not in sys.path:
        sys.path.insert(0, str(_extra))

CONFIG_EDGE_AI_DIR = _REPO_ROOT / "config" / "edge_ai"
MODEL_REGISTRY_PATH = _REPO_ROOT / "config" / "models" / "model_registry.yaml"
EDGE_AI_MODEL_REGISTRY_PATH = CONFIG_EDGE_AI_DIR / "model_registry.yaml"
