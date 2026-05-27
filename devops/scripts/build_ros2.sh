#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

log "Building ROS2 workspace with colcon"
require_cmd colcon
cd "$ROOT_DIR/ros2_ws"
source /opt/ros/${ROS_DISTRO:-humble}/setup.bash
run_cmd rosdep install --from-paths src --ignore-src -r -y --rosdistro "${ROS_DISTRO:-humble}"
run_cmd colcon build --symlink-install --event-handlers console_direct+
