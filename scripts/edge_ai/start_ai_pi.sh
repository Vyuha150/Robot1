#!/usr/bin/env bash
# Edge AI Runtime brief, Phase 10. Starts Pi-2 (AI Interaction Pi) via
# launch/edge_ai/ai_pi_edge.launch.py. Pass driver_mode:=real (plus the
# usual AI-backend args -- see that launch file's docstring) for a real
# deployment; defaults to mock for dev/CI.
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
exec ros2 launch "$ROOT_DIR/launch/edge_ai/ai_pi_edge.launch.py" "$@"
