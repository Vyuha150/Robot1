#!/usr/bin/env bash
# Type-check the rclpy-free Python cores with mypy (config in pyproject.toml).
# Node modules that import rclpy are excluded — they are thin I/O wiring over
# the typed cores and are covered by the ROS2 build/test job instead.
# Usage: scripts/typecheck.sh
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if ! command -v mypy >/dev/null 2>&1; then
  echo "mypy not found. Install with: pip install mypy" >&2
  exit 127
fi

# Keep this list in sync with the CI 'quality' job.
TARGETS=(
  devops
  ros2_ws/src/bonbon_simulation
  ros2_ws/src/bonbon_safety/bonbon_safety/core
  ros2_ws/src/bonbon_safety/bonbon_safety/testkit
)

echo "==> mypy ${TARGETS[*]}"
mypy "${TARGETS[@]}"
echo "typecheck: OK"
