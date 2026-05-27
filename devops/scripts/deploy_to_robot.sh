#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/common.sh"

usage() {
  cat <<'USAGE'
Usage: deploy_to_robot.sh --env lab_robot|staging_robot|production_robot --version VERSION [--artifact FILE --sha256 FILE] [--dry-run]
Environment variables:
  BONBON_ROBOT_HOST, BONBON_ROBOT_USER, BONBON_ROBOT_SSH_PORT
USAGE
}

ENVIRONMENT=""
VERSION=""
ARTIFACT=""
SHA256_FILE=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --env) ENVIRONMENT="$2"; shift 2 ;;
    --version) VERSION="$2"; shift 2 ;;
    --artifact) ARTIFACT="$2"; shift 2 ;;
    --sha256) SHA256_FILE="$2"; shift 2 ;;
    --dry-run) BONBON_DRY_RUN=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) fail "Unknown argument: $1" ;;
  esac
done

[[ -n "$ENVIRONMENT" ]] || fail "--env is required"
[[ -n "$VERSION" ]] || fail "--version is required"
[[ "$ENVIRONMENT" =~ ^(lab_robot|staging_robot|production_robot)$ ]] || fail "Invalid deployment environment: $ENVIRONMENT"
load_env_file "$ROOT_DIR/.env"
[[ -n "${BONBON_ROBOT_HOST:-}" ]] || fail "BONBON_ROBOT_HOST is required and must not be hardcoded"
[[ -n "${BONBON_ROBOT_USER:-}" ]] || fail "BONBON_ROBOT_USER is required"

log "Validating deployment config for $ENVIRONMENT"
run_cmd python3 "$ROOT_DIR/devops/scripts/validate_config.py" --env "$ENVIRONMENT"
if [[ -n "$ARTIFACT" || -n "$SHA256_FILE" ]]; then
  [[ -n "$ARTIFACT" && -n "$SHA256_FILE" ]] || fail "--artifact and --sha256 must be provided together"
  run_cmd python3 "$ROOT_DIR/devops/scripts/verify_release.py" --artifact "$ARTIFACT" --sha256 "$SHA256_FILE"
fi

log "Running pre-deployment safety checks"
[[ "${BONBON_OPERATOR_AUTH_CONFIRMED:-0}" == "1" || "${BONBON_DRY_RUN:-0}" == "1" ]] || fail "Operator authorization not confirmed"
[[ -f "$ROOT_DIR/deployment/ota/rollback_version" || "${BONBON_DRY_RUN:-0}" == "1" ]] || fail "Rollback version file missing"
PRECHECK_ARGS=()
if dry_run; then
  PRECHECK_ARGS=(--dry-run)
fi
run_cmd python3 "$ROOT_DIR/devops/scripts/pre_deploy_check.py" "${PRECHECK_ARGS[@]}"

SSH_TARGET="${BONBON_ROBOT_USER}@${BONBON_ROBOT_HOST}"
SSH_PORT="${BONBON_ROBOT_SSH_PORT:-22}"
REMOTE_RELEASE_DIR="/opt/bonbon/releases/$VERSION"
audit "deploy_start env=$ENVIRONMENT version=$VERSION dry_run=${BONBON_DRY_RUN:-0}"

run_cmd ssh -p "$SSH_PORT" "$SSH_TARGET" "mkdir -p '$REMOTE_RELEASE_DIR' /etc/bonbon /var/lib/bonbon /var/log/bonbon"
run_cmd rsync -az --delete -e "ssh -p $SSH_PORT" "$ROOT_DIR/deployment/compose/docker-compose.robot.yml" "$SSH_TARGET:$REMOTE_RELEASE_DIR/docker-compose.robot.yml"
run_cmd rsync -az -e "ssh -p $SSH_PORT" "$ROOT_DIR/devops/scripts/health_check.sh" "$ROOT_DIR/devops/scripts/post_deploy_check.py" "$SSH_TARGET:$REMOTE_RELEASE_DIR/"
run_cmd rsync -az -e "ssh -p $SSH_PORT" "$ROOT_DIR/devops/config/$ENVIRONMENT/" "$SSH_TARGET:/etc/bonbon/"
run_cmd ssh -p "$SSH_PORT" "$SSH_TARGET" "tmp_env=\$(mktemp); cp /etc/bonbon/runtime.env \"\$tmp_env\"; if test -f /etc/bonbon/bonbon.env; then grep -E '^(BONBON_JWT_SECRET|BONBON_ADMIN_PASSWORD)=' /etc/bonbon/bonbon.env >> \"\$tmp_env\" || true; fi; install -m 0640 \"\$tmp_env\" /etc/bonbon/bonbon.env; rm -f \"\$tmp_env\""
run_cmd ssh -p "$SSH_PORT" "$SSH_TARGET" "ln -sfn '$REMOTE_RELEASE_DIR' /opt/bonbon/current && cd /opt/bonbon/current && BONBON_IMAGE_TAG='$VERSION' docker compose -f docker-compose.robot.yml up -d"
run_cmd ssh -p "$SSH_PORT" "$SSH_TARGET" "cd /opt/bonbon/current && bash health_check.sh && python3 post_deploy_check.py"

audit "deploy_complete env=$ENVIRONMENT version=$VERSION dry_run=${BONBON_DRY_RUN:-0}"
log "Deployment completed for $ENVIRONMENT version $VERSION"
