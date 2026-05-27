#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

log "Installing BonBon development dependencies"
require_cmd sudo
run_cmd sudo apt-get update
run_cmd sudo apt-get install -y --no-install-recommends \
  python3-pip python3-venv python3-colcon-common-extensions python3-rosdep \
  python3-pytest python3-yaml curl git docker.io docker-compose-plugin

if command -v rosdep >/dev/null 2>&1; then
  run_cmd sudo rosdep init || true
  run_cmd rosdep update
fi

run_cmd python3 -m pip install --user --upgrade ruff black mypy pytest
log "Dependency install completed"
