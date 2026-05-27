#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

PACKAGES=("$@")
if [[ ${#PACKAGES[@]} -eq 0 ]]; then
  PACKAGES=(
    bonbon_operator_api bonbon_data_stores bonbon_safety bonbon_navigation
    bonbon_speech bonbon_tts bonbon_llm bonbon_perception_ai bonbon_simulation
  )
fi

require_cmd python3
for package in "${PACKAGES[@]}"; do
  package_dir="$ROOT_DIR/ros2_ws/src/$package"
  [[ -d "$package_dir" ]] || fail "Package directory missing: $package_dir"
  log "Running pytest for $package"
  (cd "$package_dir" && run_cmd python3 -m pytest tests/ -q)
done
