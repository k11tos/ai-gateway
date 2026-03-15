#!/usr/bin/env bash
set -euo pipefail

APP_DIR="${APP_DIR:-$HOME/ai-gateway}"
BRANCH="${BRANCH:-main}"
SERVICE_NAME="${SERVICE_NAME:-ai-gateway}"
HEALTH_URL="${HEALTH_URL:-http://127.0.0.1:8000/health/ready}"
STARTUP_WAIT_SECONDS="${STARTUP_WAIT_SECONDS:-5}"
HEALTHCHECK_TIMEOUT_SECONDS="${HEALTHCHECK_TIMEOUT_SECONDS:-30}"
HEALTHCHECK_INTERVAL_SECONDS="${HEALTHCHECK_INTERVAL_SECONDS:-1}"
LAST_DEPLOY_FILE=".last_deploy_commit"
RUNTIME_ENV_FILE_NAME=".deploy-runtime.env"

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
  log "HEAD already matches origin/${BRANCH} (${current_commit})."
else
  log "Updating ${current_commit} -> ${remote_commit}"
fi

log "Checking out exact origin/${BRANCH} commit"
git checkout -B "${BRANCH}" "origin/${BRANCH}"

deployed_commit="$(git rev-parse HEAD)"
if [[ "${deployed_commit}" != "${remote_commit}" ]]; then
  echo "ERROR: deployment checkout mismatch (HEAD=${deployed_commit}, origin/${BRANCH}=${remote_commit})" >&2
  exit 1
fi

runtime_app_version="${APP_VERSION:-${BRANCH}-$(git rev-parse --short=12 HEAD)}"
runtime_commit_sha="${COMMIT_SHA:-${deployed_commit}}"

runtime_env_file="${APP_DIR}/${RUNTIME_ENV_FILE_NAME}"
runtime_env_tmp="${runtime_env_file}.tmp"

log "Writing runtime metadata to ${runtime_env_file}"
{
  printf 'APP_VERSION=%s\n' "${runtime_app_version}"
  printf 'COMMIT_SHA=%s\n' "${runtime_commit_sha}"
} > "${runtime_env_tmp}"
mv "${runtime_env_tmp}" "${runtime_env_file}"

systemd_dropin_dir="/etc/systemd/system/${SERVICE_NAME}.service.d"
systemd_dropin_file="${systemd_dropin_dir}/override.conf"
log "Ensuring systemd service ${SERVICE_NAME} reads ${runtime_env_file}"
sudo mkdir -p "${systemd_dropin_dir}"
sudo tee "${systemd_dropin_file}" >/dev/null <<EOD
[Service]
EnvironmentFile=${runtime_env_file}
EOD

new_commit="${deployed_commit}"
log "Reloading systemd daemon"
sudo systemctl daemon-reload

log "Restarting systemd service: ${SERVICE_NAME}"
sudo systemctl restart "${SERVICE_NAME}"

log "Waiting ${STARTUP_WAIT_SECONDS}s for startup"
sleep "${STARTUP_WAIT_SECONDS}"

log "Running health check: ${HEALTH_URL} (timeout=${HEALTHCHECK_TIMEOUT_SECONDS}s interval=${HEALTHCHECK_INTERVAL_SECONDS}s)"
healthcheck_deadline=$((SECONDS + HEALTHCHECK_TIMEOUT_SECONDS))
while true; do
  if curl --fail --silent --show-error --max-time 10 "${HEALTH_URL}" >/dev/null; then
    break
  fi

  if (( SECONDS >= healthcheck_deadline )); then
    echo "ERROR: health check failed at ${HEALTH_URL} within ${HEALTHCHECK_TIMEOUT_SECONDS}s" >&2
    echo "Recent service logs:" >&2
    sudo journalctl -u "${SERVICE_NAME}" -n 60 --no-pager >&2 || true
    exit 1
  fi

  sleep "${HEALTHCHECK_INTERVAL_SECONDS}"
done

log "Health check passed"
log "Deployment complete: ${current_commit} -> ${new_commit}"
