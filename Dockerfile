FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends bash ca-certificates curl git nodejs npm \
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
COPY scripts/patch-vendor-models.py /app/scripts/patch-vendor-models.py

ARG HERMES_WEBUI_VERSION=unknown

RUN printf "__version__ = '%s'\n" "$HERMES_WEBUI_VERSION" > /app/vendor/hermes-webui/api/_version.py \
    && uv pip install --system --no-cache -e "/app/vendor/hermes-agent[messaging]" \
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
    HERMES_WORKSPACE_DIR=/data/workspace \
    CONTROL_PLANE_INTERNAL_WEBUI_HOST=127.0.0.1 \
    CONTROL_PLANE_INTERNAL_WEBUI_PORT=8788 \
    HERMES_GATEWAY_AUTOSTART=auto \
    PORT=8787

EXPOSE 8787

CMD ["/app/start.sh"]
