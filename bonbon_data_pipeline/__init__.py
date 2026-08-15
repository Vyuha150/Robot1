"""Dataset/training/edge-export governance layer for BonBon's AI modules.

Scope, deliberately narrow -- see docs/DATA_PIPELINE_FINAL_REPORT.md for the
full rationale: this package governs SOURCE TRAINING DATA (public corpora,
hospital-collected samples, synthetic data) and the workstation-side
training -> evaluation -> edge-export pipeline. It is NOT a second
field-failure-logging or model-registry pipeline -- those already exist and
are reused directly, not reimplemented:

  - Field failure capture, human review, regression-test generation, and
    privacy-safe anonymized event storage: `bonbon_field_learning` (already
    wired into the dashboard via bonbon_operator_api's validation_api.py).
  - Deployed MODEL artifact tracking (which model backs which capability,
    license/download/benchmark/fallback for that model): `bonbon_ai_model_registry`.
  - Live ROS2 failure-event capture on the robot itself: bonbon_data_feedback.

Pure Python, no rclpy/ROS2 import -- runs on a workstation, not the robot.
"""
