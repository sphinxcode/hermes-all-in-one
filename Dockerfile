FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update \
    && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY vendor/hermes-agent /app/vendor/hermes-agent
COPY vendor/hermes-webui /app/vendor/hermes-webui
COPY control_plane /app/control_plane
COPY requirements-control-plane.txt /app/requirements-control-plane.txt
COPY start.sh /app/start.sh

ARG HERMES_WEBUI_VERSION=unknown

RUN printf "__version__ = '%s'\n" "$HERMES_WEBUI_VERSION" > /app/vendor/hermes-webui/api/_version.py \
    && cd /app/vendor/hermes-agent/web \
    && npm ci --prefer-offline --no-audit \
    && npm run build \
    && npm cache clean --force \
    && cd /app \
    && uv pip install --system --no-cache -e "/app/vendor/hermes-agent[messaging]" \
    && uv pip install --system --no-cache fastapi "uvicorn[standard]" \
    && uv pip install --system --no-cache -r /app/vendor/hermes-webui/requirements.txt \
    && uv pip install --system --no-cache -r /app/requirements-control-plane.txt \
    && uv pip install --system --no-cache "mcp>=1.24.0" \
    && chmod +x /app/start.sh \
    && mkdir -p /data/.hermes /data/webui /data/workspace \
    && touch /.within_container

ENV HOME=/data \
    HERMES_HOME=/data/.hermes \
    HERMES_CONFIG_PATH=/data/.hermes/config.yaml \
    HERMES_WEBUI_STATE_DIR=/data/webui \
    HERMES_WEBUI_AGENT_DIR=/app/vendor/hermes-agent \
    HERMES_WEB_DIST=/app/vendor/hermes-agent/hermes_cli/web_dist \
    HERMES_WORKSPACE_DIR=/data/workspace \
    CONTROL_PLANE_INTERNAL_WEBUI_HOST=127.0.0.1 \
    CONTROL_PLANE_INTERNAL_WEBUI_PORT=8788 \
    CONTROL_PLANE_INTERNAL_DASHBOARD_HOST=127.0.0.1 \
    CONTROL_PLANE_INTERNAL_DASHBOARD_PORT=9119 \
    HERMES_GATEWAY_AUTOSTART=auto \
    PORT=8787

EXPOSE 8787

CMD ["/app/start.sh"]
