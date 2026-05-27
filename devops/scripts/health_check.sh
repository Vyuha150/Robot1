#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"
load_env_file "${1:-$ROOT_DIR/.env}"

log "Running BonBon health check"
services=(bonbon-core bonbon-navigation bonbon-perception bonbon-speech bonbon-tts bonbon-safety bonbon-dashboard bonbon-monitoring)
failed=0
for service in "${services[@]}"; do
  if command -v systemctl >/dev/null 2>&1; then
    if ! systemctl is-active --quiet "$service.service"; then
      log "Service not active: $service"
      failed=1
    fi
  else
    log "systemctl unavailable; skipping service state for $service"
  fi
done

if command -v curl >/dev/null 2>&1; then
  curl -fsS "http://127.0.0.1:${BONBON_DASHBOARD_PORT:-8080}/health" >/dev/null || log "Dashboard health endpoint unavailable"
  curl -fsS "http://127.0.0.1:${BONBON_PROMETHEUS_PORT:-9090}/-/healthy" >/dev/null || log "Prometheus health endpoint unavailable"
fi

[[ "$failed" -eq 0 ]] || fail "One or more BonBon services are unhealthy"
log "Health check completed"
