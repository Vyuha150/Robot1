#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

log() {
  printf '[bonbon-devops] %s\n' "$*"
}

audit() {
  local audit_file="${BONBON_AUDIT_LOG:-$ROOT_DIR/deployment/logs/deployment_audit.log}"
  mkdir -p "$(dirname "$audit_file")"
  printf '%s user=%s action=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "${USER:-unknown}" "$*" >> "$audit_file"
}

fail() {
  printf '[bonbon-devops] ERROR: %s\n' "$*" >&2
  exit 1
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

dry_run() {
  [[ "${BONBON_DRY_RUN:-0}" == "1" || "${DRY_RUN:-0}" == "1" ]]
}

run_cmd() {
  if dry_run; then
    log "DRY RUN: $*"
  else
    "$@"
  fi
}

load_env_file() {
  local env_file="${1:-$ROOT_DIR/.env}"
  if [[ -f "$env_file" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$env_file"
    set +a
  fi
}
