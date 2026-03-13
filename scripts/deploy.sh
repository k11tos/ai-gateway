#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/ai-gateway}"
BRANCH="${BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-ai-gateway}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health/ready}"
STARTUP_WAIT_SECONDS="${STARTUP_WAIT_SECONDS:-5}"
LAST_DEPLOY_FILE=".last_deploy_commit"

APP_DIR="${APP_DIR/#\~/$HOME}"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"
}

require_cmd() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "ERROR: required command not found: $1" >&2
    exit 1
  }
}

require_cmd git
require_cmd curl
require_cmd sudo
require_cmd systemctl

log "Starting deployment"
log "APP_DIR=${APP_DIR} BRANCH=${BRANCH} SERVICE=${SERVICE_NAME}"

if [[ ! -d "${APP_DIR}" ]]; then
  echo "ERROR: APP_DIR does not exist: ${APP_DIR}" >&2
  exit 1
fi

cd "${APP_DIR}"

if [[ ! -d .git ]]; then
  echo "ERROR: ${APP_DIR} is not a git repository" >&2
  exit 1
fi

current_commit="$(git rev-parse HEAD)"
echo "${current_commit}" > "${LAST_DEPLOY_FILE}"
log "Recorded previous commit in ${LAST_DEPLOY_FILE}: ${current_commit}"

log "Fetching latest origin/${BRANCH}"
git fetch --prune origin "${BRANCH}"

remote_commit="$(git rev-parse "origin/${BRANCH}")"
if [[ "${current_commit}" == "${remote_commit}" ]]; then
  log "Already at latest commit (${current_commit}). Restarting service only."
else
  log "Updating ${current_commit} -> ${remote_commit}"
  git pull --ff-only origin "${BRANCH}"
fi

new_commit="$(git rev-parse HEAD)"
log "Restarting systemd service: ${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

log "Waiting ${STARTUP_WAIT_SECONDS}s for startup"
sleep "${STARTUP_WAIT_SECONDS}"

log "Running health check: ${HEALTH_URL}"
if ! curl --fail --silent --show-error --max-time 10 "${HEALTH_URL}" >/dev/null; then
  echo "ERROR: health check failed at ${HEALTH_URL}" >&2
  echo "Recent service logs:" >&2
  sudo journalctl -u "${SERVICE_NAME}" -n 60 --no-pager >&2 || true
  exit 1
fi

log "Health check passed"
log "Deployment complete: ${current_commit} -> ${new_commit}"
