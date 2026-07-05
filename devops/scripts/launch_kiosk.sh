#!/usr/bin/env bash
# Launch the Pi-1 touchscreen dashboard in kiosk mode.
#
# Resolves docs/HARDWARE_SOFTWARE_GAP_REPORT.md item 6 ("no kiosk-mode
# touchscreen config") -- this is the "bonbon-dashboard-frontend.service"
# referenced by config/distributed/pi_ui_api.yaml's boot_order (rank 2,
# "requires ui-api healthy"), which did not exist as a real script before
# this change.
#
# Waits for bonbon_operator_api's health endpoint to respond before
# opening the browser -- a kiosk browser pointed at a dead backend is a
# blank/error screen an operator can't recover from without SSH access,
# so this is a real dependency check, not decoration.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
load_env_file "${1:-$ROOT_DIR/.env}"

DASHBOARD_PORT="${BONBON_DASHBOARD_PORT:-8080}"
DASHBOARD_URL="http://127.0.0.1:${DASHBOARD_PORT}/"
WAIT_TIMEOUT_SEC="${BONBON_KIOSK_WAIT_TIMEOUT_SEC:-60}"

require_cmd curl

log "Waiting up to ${WAIT_TIMEOUT_SEC}s for dashboard API at ${DASHBOARD_URL}health"
waited=0
until curl -fsS "http://127.0.0.1:${DASHBOARD_PORT}/health" >/dev/null 2>&1; do
  if [[ "$waited" -ge "$WAIT_TIMEOUT_SEC" ]]; then
    fail "Dashboard API never became healthy after ${WAIT_TIMEOUT_SEC}s -- refusing to open a kiosk browser against a dead backend"
  fi
  sleep 2
  waited=$((waited + 2))
done
log "Dashboard API healthy after ${waited}s"

BROWSER_BIN=""
for candidate in chromium-browser chromium google-chrome; do
  if command -v "$candidate" >/dev/null 2>&1; then
    BROWSER_BIN="$candidate"
    break
  fi
done
[[ -n "$BROWSER_BIN" ]] || fail "No Chromium/Chrome binary found -- install chromium-browser on Pi-1"

log "Launching ${BROWSER_BIN} in kiosk mode against ${DASHBOARD_URL}"
exec "$BROWSER_BIN" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  "$DASHBOARD_URL"
