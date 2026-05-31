#!/usr/bin/env bash
# Install system + Python + ROS2 dependencies.
# Canonical entry point — delegates to the battle-tested implementation in
# devops/scripts/ (which is also wired into the Docker images).
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT_DIR/devops/scripts/install_dependencies.sh" "$@"
