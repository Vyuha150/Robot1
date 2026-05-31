#!/usr/bin/env bash
# Run the BonBon test suites.
#
#   scripts/test.sh --no-ros2   Pure-Python suites only (no ROS2 / hardware).
#                               Fast; this is what the CI 'python-tests' job runs.
#   scripts/test.sh             Full suites: delegates to devops/scripts/run_tests.sh
#                               (expects a sourced ROS2 workspace for node tests).
#
# The --no-ros2 mode runs the safety-critical decision/AI cores that the legacy
# CI never exercised: safety, behavior_engine, actuation, spatial, gesture,
# affective_ai, plus the 30 real-world scenarios.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT_DIR/ros2_ws/src"
cd "$ROOT_DIR"

run_pkg() {  # run_pkg <package> [extra pytest args...]
  local pkg="$1"; shift || true
  local dir="$SRC/$pkg"
  [[ -d "$dir" ]] || { echo "skip (missing): $pkg"; return 0; }
  echo "==> pytest $pkg"
  (cd "$dir" && python -m pytest tests/ -q -p no:cacheprovider "$@")
}

if [[ "${1:-}" == "--no-ros2" ]]; then
  echo "### Pure-Python test suites (no ROS2) ###"
  # bonbon_safety: exclude the rclpy-dependent node tests (run in the ROS2 job).
  (cd "$SRC/bonbon_safety" && python -m pytest tests/ -q -p no:cacheprovider \
      --ignore=tests/integration \
      --ignore=tests/simulation \
      --ignore=tests/test_watchdog.py \
      --ignore=tests/test_safety_gate.py)
  run_pkg bonbon_behavior_engine
  run_pkg bonbon_actuation
  run_pkg bonbon_spatial
  run_pkg bonbon_gesture
  run_pkg bonbon_affective_ai
  echo "### All pure-Python suites passed ###"
else
  echo "### Full test suites (ROS2 workspace) ###"
  exec bash "$ROOT_DIR/devops/scripts/run_tests.sh" "$@"
fi
