#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

DEST="${1:-$ROOT_DIR/deployment/logs/bonbon_logs_$(date -u +%Y%m%dT%H%M%SZ)}"
run_cmd mkdir -p "$DEST"
log "Collecting logs into $DEST"

if command -v journalctl >/dev/null 2>&1; then
  for service in bonbon-core bonbon-navigation bonbon-perception bonbon-speech bonbon-tts bonbon-safety bonbon-dashboard bonbon-monitoring; do
    run_cmd journalctl -u "$service.service" --since "24 hours ago" > "$DEST/$service.journal.log" || true
  done
fi

if [[ -d /var/log/bonbon ]]; then
  run_cmd cp -a /var/log/bonbon "$DEST/runtime" || true
fi
log "Log collection completed"
