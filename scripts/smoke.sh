#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
IMAGE_TAG="hermes-control-plane-smoke:local"
CONTAINER_NAME="hermes-control-plane-smoke"
HOST_PORT="${SMOKE_PORT:-18787}"
CONTAINER_PORT="${SMOKE_CONTAINER_PORT:-18999}"
DATA_DIR="${SMOKE_DATA_DIR:-${ROOT_DIR}/.tmp-smoke-data}"
WEBUI_PASSWORD="${SMOKE_WEBUI_PASSWORD:-smoke-webui-password}"
ADMIN_PASSWORD="${SMOKE_ADMIN_PASSWORD:-smoke-admin-password}"
COOKIE_JAR="${DATA_DIR}/admin-cookies.txt"

cleanup() {
  docker rm -f "${CONTAINER_NAME}" >/dev/null 2>&1 || true
}
trap cleanup EXIT

require() {
  command -v "$1" >/dev/null 2>&1 || {
    echo "[smoke] missing required command: $1" >&2
    exit 1
  }
}

wait_for_health() {
  local url="$1"
  for ((i=1; i<=60; i++)); do
    if curl --silent --show-error --fail "$url" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  echo "[smoke] timed out waiting for health: ${url}" >&2
  return 1
}

assert_eq() {
  local actual="$1"
  local expected="$2"
  local message="$3"
  if [[ "$actual" != "$expected" ]]; then
    echo "[smoke] assertion failed: ${message}" >&2
    echo "  expected: ${expected}" >&2
    echo "  actual:   ${actual}" >&2
    exit 1
  fi
}

require docker
require curl
require python3

rm -rf "${DATA_DIR}"
mkdir -p "${DATA_DIR}"
cleanup

cd "${ROOT_DIR}"

echo "[smoke] building image ${IMAGE_TAG}"
docker build -t "${IMAGE_TAG}" .

echo "[smoke] starting container with PORT=${CONTAINER_PORT}"
docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  -e PORT="${CONTAINER_PORT}" \
  -e HERMES_WEBUI_PASSWORD="${WEBUI_PASSWORD}" \
  -e HERMES_ADMIN_PASSWORD="${ADMIN_PASSWORD}" \
  -v "${DATA_DIR}:/data" \
  "${IMAGE_TAG}" >/dev/null

wait_for_health "http://127.0.0.1:${HOST_PORT}/health"

echo "[smoke] checking public routing"
root_status="$(curl --silent --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:${HOST_PORT}/")"
admin_status="$(curl --silent --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:${HOST_PORT}/admin")"
login_status="$(curl --silent --output /dev/null --write-out '%{http_code}' "http://127.0.0.1:${HOST_PORT}/admin/login")"
case "$root_status" in
  200|302|303) ;;
  *)
    echo "[smoke] expected / to serve or redirect to WebUI auth, got ${root_status}" >&2
    exit 1
    ;;
esac
case "$admin_status" in
  302|303) ;;
  *)
    echo "[smoke] expected /admin to require auth, got ${admin_status}" >&2
    exit 1
    ;;
esac
assert_eq "$login_status" "200" "/admin/login should render"

echo "[smoke] logging into /admin"
curl --silent --show-error --fail \
  -c "${COOKIE_JAR}" \
  -d "password=${ADMIN_PASSWORD}" \
  -X POST "http://127.0.0.1:${HOST_PORT}/admin/login" \
  -o /dev/null >/dev/null

status_json="$(curl --silent --show-error --fail -b "${COOKIE_JAR}" "http://127.0.0.1:${HOST_PORT}/admin/api/status")"
python3 - <<'PY' "$status_json"
import json, sys
payload = json.loads(sys.argv[1])
assert payload['paths']['config_path'] == '/data/.hermes/config.yaml'
assert payload['paths']['webui_state_dir'] == '/data/webui'
assert payload['paths']['workspace_dir'] == '/data/workspace'
print('[smoke] admin status paths OK')
PY

echo "[smoke] exercising control-plane actions"
curl --silent --show-error --fail -b "${COOKIE_JAR}" -X POST "http://127.0.0.1:${HOST_PORT}/admin/api/webui/restart" -o /dev/null >/dev/null
wait_for_health "http://127.0.0.1:${HOST_PORT}/health"
curl --silent --show-error --fail -b "${COOKIE_JAR}" -X POST "http://127.0.0.1:${HOST_PORT}/admin/api/gateway/restart" -o /dev/null >/dev/null
wait_for_health "http://127.0.0.1:${HOST_PORT}/health"

signing_before="$(docker exec "${CONTAINER_NAME}" /bin/sh -lc 'sha256sum /data/webui/.signing_key | awk "{print \$1}"')"

echo "[smoke] restarting container with same /data volume"
docker rm -f "${CONTAINER_NAME}" >/dev/null

docker run -d \
  --name "${CONTAINER_NAME}" \
  -p "${HOST_PORT}:${CONTAINER_PORT}" \
  -e PORT="${CONTAINER_PORT}" \
  -e HERMES_WEBUI_PASSWORD="${WEBUI_PASSWORD}" \
  -e HERMES_ADMIN_PASSWORD="${ADMIN_PASSWORD}" \
  -v "${DATA_DIR}:/data" \
  "${IMAGE_TAG}" >/dev/null

wait_for_health "http://127.0.0.1:${HOST_PORT}/health"
signing_after="$(docker exec "${CONTAINER_NAME}" /bin/sh -lc 'sha256sum /data/webui/.signing_key | awk "{print \$1}"')"
assert_eq "$signing_after" "$signing_before" "WebUI signing key should persist across restart"

echo "[smoke] PASS"
