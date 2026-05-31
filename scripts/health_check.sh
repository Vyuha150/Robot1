#!/usr/bin/env bash
# Check health of the running robot stack.
# Canonical entry point — delegates to the battle-tested implementation in
# devops/scripts/ (which is also wired into the Docker images).
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT_DIR/devops/scripts/health_check.sh" "$@"
