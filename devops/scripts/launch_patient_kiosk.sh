#!/usr/bin/env bash
# Launch the patient-facing touchscreen kiosk in kiosk mode.
#
# Mirrors launch_kiosk.sh (Pi-1's staff dashboard) but points at the
# bonbon_patient_kiosk frontend/backend on their own port and, per the
# plan decision recorded when that package was created, is meant to run
# on a dedicated screen/host -- never the same kiosk browser instance as
# the staff dashboard.
#
# Waits for bonbon_patient_kiosk's health endpoint before opening the
# browser -- a kiosk browser pointed at a dead backend leaves a patient
# with a blank/error screen and no way to check in.
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
load_env_file "${1:-$ROOT_DIR/.env}"

KIOSK_API_PORT="${BONBON_PATIENT_KIOSK_API_PORT:-8090}"
KIOSK_FRONTEND_URL="${BONBON_PATIENT_KIOSK_FRONTEND_URL:-http://127.0.0.1:3100/}"
WAIT_TIMEOUT_SEC="${BONBON_KIOSK_WAIT_TIMEOUT_SEC:-60}"

require_cmd curl

log "Waiting up to ${WAIT_TIMEOUT_SEC}s for patient kiosk API at 127.0.0.1:${KIOSK_API_PORT}/health"
waited=0
until curl -fsS "http://127.0.0.1:${KIOSK_API_PORT}/health" >/dev/null 2>&1; do
  if [[ "$waited" -ge "$WAIT_TIMEOUT_SEC" ]]; then
    fail "Patient kiosk API never became healthy after ${WAIT_TIMEOUT_SEC}s -- refusing to open a kiosk browser against a dead backend"
  fi
  sleep 2
  waited=$((waited + 2))
done
log "Patient kiosk API healthy after ${waited}s"

BROWSER_BIN=""
for candidate in chromium-browser chromium google-chrome; do
  if command -v "$candidate" >/dev/null 2>&1; then
    BROWSER_BIN="$candidate"
    break
  fi
done
[[ -n "$BROWSER_BIN" ]] || fail "No Chromium/Chrome binary found -- install chromium-browser on the kiosk host"

log "Launching ${BROWSER_BIN} in kiosk mode against ${KIOSK_FRONTEND_URL}"
exec "$BROWSER_BIN" \
  --kiosk \
  --noerrdialogs \
  --disable-infobars \
  --disable-session-crashed-bubble \
  --disable-pinch \
  --overscroll-history-navigation=0 \
  --check-for-update-interval=31536000 \
  "$KIOSK_FRONTEND_URL"
