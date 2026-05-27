#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

SCENARIO="${1:-hospital_corridor_navigation}"
log "Running simulation smoke scenario: $SCENARIO"
cd "$ROOT_DIR/ros2_ws/src/bonbon_simulation"
run_cmd python3 -m pytest tests/test_simulation_suite.py::test_ci_headless_run -q
run_cmd python3 -m bonbon_simulation.core.runner "scenarios/${SCENARIO}.yaml" --config config/simulation_params.yaml
