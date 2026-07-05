#!/usr/bin/env bash
# Launch the Pi-1 touchscreen dashboard in kiosk mode.
# Canonical entry point — delegates to the implementation in
# devops/scripts/ (also wired into bonbon-dashboard-frontend.service).
set -Eeuo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec bash "$ROOT_DIR/devops/scripts/launch_kiosk.sh" "$@"
