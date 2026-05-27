#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

ENVIRONMENT="${BONBON_ENV:-lab_robot}"
ROLLBACK_VERSION="${1:-}"
[[ -n "$ROLLBACK_VERSION" ]] || ROLLBACK_VERSION="$(cat "$ROOT_DIR/deployment/ota/rollback_version" 2>/dev/null || true)"
[[ -n "$ROLLBACK_VERSION" ]] || fail "Rollback version is required"
load_env_file "$ROOT_DIR/.env"
[[ -n "${BONBON_ROBOT_HOST:-}" ]] || fail "BONBON_ROBOT_HOST is required"

log "Rolling back $ENVIRONMENT robot to $ROLLBACK_VERSION"
SSH_TARGET="${BONBON_ROBOT_USER:-bonbon}@${BONBON_ROBOT_HOST}"
SSH_PORT="${BONBON_ROBOT_SSH_PORT:-22}"
audit "rollback_start env=$ENVIRONMENT version=$ROLLBACK_VERSION dry_run=${BONBON_DRY_RUN:-0}"
run_cmd ssh -p "$SSH_PORT" "$SSH_TARGET" "test -d '/opt/bonbon/releases/$ROLLBACK_VERSION'"
run_cmd ssh -p "$SSH_PORT" "$SSH_TARGET" "ln -sfn '/opt/bonbon/releases/$ROLLBACK_VERSION' /opt/bonbon/current && cd /opt/bonbon/current && BONBON_IMAGE_TAG='$ROLLBACK_VERSION' docker compose -f docker-compose.robot.yml up -d"
run_cmd ssh -p "$SSH_PORT" "$SSH_TARGET" "cd /opt/bonbon/current && bash health_check.sh && python3 post_deploy_check.py"
audit "rollback_complete env=$ENVIRONMENT version=$ROLLBACK_VERSION dry_run=${BONBON_DRY_RUN:-0}"
log "Rollback completed"
