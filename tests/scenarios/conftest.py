"""Makes every ROS2 package's pure-Python core importable from this
cross-package scenario suite, without requiring a sourced ROS2 workspace.

Each bonbon_* package under ros2_ws/src is a separate ament_python package
with its own isolated tests/ directory — none of them have sibling packages
on sys.path by default. This suite intentionally exercises several packages
together (object_intelligence -> multi_person_tracker -> gesture ->
speaker_intelligence -> human_state_fusion -> behavior_engine), so it needs
all of them importable at once.
"""

from __future__ import annotations

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parents[2] / "ros2_ws" / "src"

_PACKAGES = [
    "bonbon_object_intelligence",
    "bonbon_multi_person_tracker",
    "bonbon_gesture",
    "bonbon_speaker_intelligence",
    "bonbon_human_state_fusion",
    "bonbon_behavior_engine",
    "bonbon_affective_ai",
    "bonbon_safety",
    "bonbon_perception_efficiency",
    "bonbon_data_feedback",
    "bonbon_data_stores",
    "bonbon_llm",
]

for _pkg in _PACKAGES:
    _path = str(_SRC / _pkg)
    if _path not in sys.path:
        sys.path.insert(0, _path)
