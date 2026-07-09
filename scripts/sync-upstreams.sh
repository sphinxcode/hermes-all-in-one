#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

AGENT_REMOTE_NAME="hermes-agent-upstream"
AGENT_REMOTE_URL="https://github.com/NousResearch/hermes-agent.git"
AGENT_REMOTE_REF="main"
AGENT_PREFIX="vendor/hermes-agent"

WEBUI_REMOTE_NAME="hermes-webui-upstream"
WEBUI_REMOTE_URL="https://github.com/nesquena/hermes-webui.git"
WEBUI_REMOTE_REF="master"
WEBUI_PREFIX="vendor/hermes-webui"

run() {
  echo "+ $*"
  "$@"
}

fail() {
  echo "[sync] $*" >&2
  exit 1
}

ensure_clean_tree() {
  git diff --quiet || fail "working tree has unstaged changes"
  git diff --cached --quiet || fail "index has staged changes"
  if [[ -n "$(git ls-files --others --exclude-standard)" ]]; then
    fail "working tree has untracked files"
  fi
}

ensure_remote() {
  local name="$1"
  local url="$2"
  local current
  current="$(git remote get-url "$name" 2>/dev/null || true)"
  if [[ -z "$current" ]]; then
    run git remote add "$name" "$url"
    return
  fi
  if [[ "$current" != "$url" ]]; then
    fail "remote $name points to $current, expected $url"
  fi
}

ensure_clean_tree
ensure_remote "$AGENT_REMOTE_NAME" "$AGENT_REMOTE_URL"
ensure_remote "$WEBUI_REMOTE_NAME" "$WEBUI_REMOTE_URL"

run git fetch "$AGENT_REMOTE_NAME" "$AGENT_REMOTE_REF"
run git fetch "$WEBUI_REMOTE_NAME" "$WEBUI_REMOTE_REF"
run git subtree pull --prefix="$AGENT_PREFIX" "$AGENT_REMOTE_NAME" "$AGENT_REMOTE_REF" --squash
run git subtree pull --prefix="$WEBUI_PREFIX" "$WEBUI_REMOTE_NAME" "$WEBUI_REMOTE_REF" --squash

# NOTE: the webui model-list patch (scripts/patch-vendor-models.py) is no
# longer run or committed here. Committing its diff into this path caused a
# recurring, unresolvable subtree conflict every subsequent sync (upstream
# and our own patch kept editing the same lines). It now runs at container
# boot instead (see start.sh), directly on the deployed filesystem, never
# touching git history -- so vendor/hermes-webui/api/config.py stays
# byte-identical to upstream here, and this pull never conflicts on that
# file's account again.

echo "[sync] upstream refresh complete"
echo "[sync] next steps:"
echo "  1. Review changes in vendor/ and root integration files"
echo "  2. Run ./scripts/smoke.sh"
echo "  3. Redeploy only after the smoke checks pass"
