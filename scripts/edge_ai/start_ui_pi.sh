#!/usr/bin/env bash
# Edge AI Runtime brief, Phase 10. Starts Pi-1 (UI/Supervisor Pi) via
# launch/edge_ai/ui_pi_edge.launch.py -- a thin wrapper, all real
# startup logic lives in that launch file / the bringup packages it
# composes.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec ros2 launch "$ROOT_DIR/launch/edge_ai/ui_pi_edge.launch.py" "$@"
