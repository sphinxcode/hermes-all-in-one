#!/usr/bin/env bash
set -euo pipefail

export HOME="${HOME:-/data}"
export HERMES_HOME="${HERMES_HOME:-/data/.hermes}"
export HERMES_CONFIG_PATH="${HERMES_CONFIG_PATH:-${HERMES_HOME}/config.yaml}"
export HERMES_WEBUI_STATE_DIR="${HERMES_WEBUI_STATE_DIR:-/data/webui}"
export HERMES_WEBUI_AGENT_DIR="${HERMES_WEBUI_AGENT_DIR:-/app/vendor/hermes-agent}"
export HERMES_WORKSPACE_DIR="${HERMES_WORKSPACE_DIR:-/data/workspace}"
export CONTROL_PLANE_HOST="${CONTROL_PLANE_HOST:-0.0.0.0}"
export CONTROL_PLANE_INTERNAL_WEBUI_HOST="${CONTROL_PLANE_INTERNAL_WEBUI_HOST:-127.0.0.1}"
export CONTROL_PLANE_INTERNAL_WEBUI_PORT="${CONTROL_PLANE_INTERNAL_WEBUI_PORT:-8788}"
export CONTROL_PLANE_INTERNAL_DASHBOARD_HOST="${CONTROL_PLANE_INTERNAL_DASHBOARD_HOST:-127.0.0.1}"
export CONTROL_PLANE_INTERNAL_DASHBOARD_PORT="${CONTROL_PLANE_INTERNAL_DASHBOARD_PORT:-9119}"
export HERMES_GATEWAY_AUTOSTART="${HERMES_GATEWAY_AUTOSTART:-auto}"
export PYTHONUNBUFFERED=1

mkdir -p \
  /data \
  "${HERMES_HOME}" \
  "${HERMES_HOME}/sessions" \
  "${HERMES_HOME}/skills" \
  "${HERMES_HOME}/optional-skills" \
  "${HERMES_HOME}/pairing" \
  "${HERMES_WEBUI_STATE_DIR}" \
  "${HERMES_WORKSPACE_DIR}"

# Seed pairing files with valid JSON (gateway expects parseable files, not 0-byte)
for f in telegram-approved.json telegram-pending.json _rate_limits.json; do
  target="${HERMES_HOME}/pairing/${f}"
  [ -s "${target}" ] || echo '{}' > "${target}"
done
chmod 600 "${HERMES_HOME}"/pairing/*.json 2>/dev/null || true

# Seed vendored built-in skills on first run (no-clobber preserves user edits)
if [ -d "/app/vendor/hermes-agent/skills" ]; then
  cp -rn /app/vendor/hermes-agent/skills/. "${HERMES_HOME}/skills/" 2>/dev/null || true
fi
if [ -d "/app/vendor/hermes-agent/optional-skills" ]; then
  cp -rn /app/vendor/hermes-agent/optional-skills/. "${HERMES_HOME}/optional-skills/" 2>/dev/null || true
fi

echo "[start] launching Hermes control plane on 0.0.0.0:${PORT:-8787}"
echo "[start] internal WebUI target ${CONTROL_PLANE_INTERNAL_WEBUI_HOST}:${CONTROL_PLANE_INTERNAL_WEBUI_PORT}"
echo "[start] internal Dashboard target ${CONTROL_PLANE_INTERNAL_DASHBOARD_HOST}:${CONTROL_PLANE_INTERNAL_DASHBOARD_PORT}"
echo "[start] gateway autostart mode ${HERMES_GATEWAY_AUTOSTART}"

exec uvicorn control_plane.server:app --host "${CONTROL_PLANE_HOST}" --port "${PORT:-8787}"
