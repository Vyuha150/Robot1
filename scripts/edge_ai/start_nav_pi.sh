#!/usr/bin/env bash
# Edge AI Runtime brief, Phase 10. Starts Pi-3 (Navigation/Safety Pi) via
# launch/edge_ai/nav_pi_edge.launch.py. Pass driver_mode:=real for a
# real deployment; defaults to mock for dev/CI.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec ros2 launch "$ROOT_DIR/launch/edge_ai/nav_pi_edge.launch.py" "$@"
