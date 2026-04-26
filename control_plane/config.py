from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

_DEFAULT_HOME = Path(os.getenv("HOME", "/data")).expanduser().resolve()
_DEFAULT_HERMES_HOME = Path(os.getenv("HERMES_HOME", str(_DEFAULT_HOME / ".hermes"))).expanduser().resolve()
DATA_DIR = Path(os.getenv("HERMES_DATA_DIR", str(_DEFAULT_HERMES_HOME.parent))).expanduser().resolve()
HOME_DIR = _DEFAULT_HOME
HERMES_HOME = _DEFAULT_HERMES_HOME
HERMES_CONFIG_PATH = Path(os.getenv("HERMES_CONFIG_PATH", str(HERMES_HOME / "config.yaml"))).expanduser().resolve()
HERMES_ENV_PATH = HERMES_HOME / ".env"
WEBUI_STATE_DIR = Path(os.getenv("HERMES_WEBUI_STATE_DIR", str(DATA_DIR / "webui"))).expanduser().resolve()
WORKSPACE_DIR = Path(os.getenv("HERMES_WORKSPACE_DIR", str(DATA_DIR / "workspace"))).expanduser().resolve()
WEBUI_AGENT_DIR = Path(os.getenv("HERMES_WEBUI_AGENT_DIR", "/app/vendor/hermes-agent")).expanduser().resolve()

PUBLIC_HOST = os.getenv("CONTROL_PLANE_HOST", "0.0.0.0")
PUBLIC_PORT = int(os.getenv("PORT", os.getenv("CONTROL_PLANE_PORT", "8787")))
INTERNAL_WEBUI_HOST = os.getenv("CONTROL_PLANE_INTERNAL_WEBUI_HOST", "127.0.0.1")
INTERNAL_WEBUI_PORT = int(os.getenv("CONTROL_PLANE_INTERNAL_WEBUI_PORT", "8788"))
INTERNAL_WEBUI_BASE = f"http://{INTERNAL_WEBUI_HOST}:{INTERNAL_WEBUI_PORT}"
INTERNAL_DASHBOARD_HOST = os.getenv("CONTROL_PLANE_INTERNAL_DASHBOARD_HOST", "127.0.0.1")
INTERNAL_DASHBOARD_PORT = int(os.getenv("CONTROL_PLANE_INTERNAL_DASHBOARD_PORT", "9119"))
INTERNAL_DASHBOARD_BASE = f"http://{INTERNAL_DASHBOARD_HOST}:{INTERNAL_DASHBOARD_PORT}"
GATEWAY_AUTOSTART = os.getenv("HERMES_GATEWAY_AUTOSTART", "auto").strip().lower() or "auto"
ADMIN_USERNAME = os.getenv("HERMES_ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("HERMES_ADMIN_PASSWORD", os.getenv("HERMES_WEBUI_PASSWORD", "")).strip()
ADMIN_SESSION_TTL = int(os.getenv("HERMES_ADMIN_SESSION_TTL", str(24 * 60 * 60)))
ADMIN_COOKIE_NAME = "hermes_admin_session"
STATUS_CACHE_TTL = float(os.getenv("CONTROL_PLANE_STATUS_CACHE_TTL", "2.0"))


def deployment_metadata() -> dict[str, str]:
    return {
        "public_domain": os.getenv("RAILWAY_PUBLIC_DOMAIN", ""),
        "snapshot_id": os.getenv("RAILWAY_SNAPSHOT_ID", ""),
        "git_commit_sha": os.getenv("RAILWAY_GIT_COMMIT_SHA", ""),
        "git_branch": os.getenv("RAILWAY_GIT_BRANCH", ""),
        "git_repo_owner": os.getenv("RAILWAY_GIT_REPO_OWNER", ""),
        "git_repo_name": os.getenv("RAILWAY_GIT_REPO_NAME", ""),
    }

_SUPPORTED_PROVIDER_SETUPS: dict[str, dict[str, Any]] = {
    "openrouter": {
        "label": "OpenRouter",
        "env_var": "OPENROUTER_API_KEY",
        "default_model": "anthropic/claude-sonnet-4.6",
        "requires_base_url": False,
    },
    "anthropic": {
        "label": "Anthropic",
        "env_var": "ANTHROPIC_API_KEY",
        "default_model": "claude-sonnet-4.6",
        "requires_base_url": False,
    },
    "openai": {
        "label": "OpenAI",
        "env_var": "OPENAI_API_KEY",
        "default_model": "gpt-4o",
        "default_base_url": "https://api.openai.com/v1",
        "requires_base_url": False,
    },
    "custom": {
        "label": "Custom OpenAI-compatible",
        "env_var": "OPENAI_API_KEY",
        "default_model": "gpt-4o-mini",
        "requires_base_url": True,
    },
}

UNSUPPORTED_PROVIDER_NOTE = (
    "OAuth and advanced provider flows such as OpenAI Codex, ChatGPT-style subscription login, "
    "Nous Portal, and GitHub Copilot are still advanced/manual in hosted Railway deployments. "
    "Use terminal-first Hermes auth/model flows for those providers instead of relying on in-browser OAuth."
)

CHANNEL_FIELDS: dict[str, dict[str, str]] = {
    "telegram": {
        "label": "Telegram",
        "primary": "TELEGRAM_BOT_TOKEN",
        "secondary": "TELEGRAM_ALLOWED_USERS",
        "hint": "Bot token, plus optional allowlist or home channel settings in .env.",
    },
    "discord": {
        "label": "Discord",
        "primary": "DISCORD_BOT_TOKEN",
        "secondary": "DISCORD_ALLOWED_USERS",
        "hint": "Bot token, plus optional allowlist.",
    },
    "slack": {
        "label": "Slack",
        "primary": "SLACK_BOT_TOKEN",
        "secondary": "SLACK_APP_TOKEN",
        "hint": "Bot token and optional app token.",
    },
    "whatsapp": {
        "label": "WhatsApp",
        "primary": "WHATSAPP_ENABLED",
        "secondary": "",
        "hint": "Set to 1/true when WhatsApp is configured externally.",
    },
    "email": {
        "label": "Email",
        "primary": "EMAIL_ADDRESS",
        "secondary": "EMAIL_PASSWORD",
        "hint": "Mailbox address and password/app password.",
    },
}

CHANNEL_ENV_KEYS = tuple(
    key for mapping in CHANNEL_FIELDS.values() for key in (mapping["primary"], mapping["secondary"]) if key
)

_PROVIDER_ENV_VARS = {meta["env_var"] for meta in _SUPPORTED_PROVIDER_SETUPS.values()}


def ensure_runtime_dirs() -> None:
    for path in (DATA_DIR, HERMES_HOME, WEBUI_STATE_DIR, WORKSPACE_DIR, HERMES_HOME / "sessions", HERMES_HOME / "skills"):
        path.mkdir(parents=True, exist_ok=True)


def load_env_file(env_path: Path = HERMES_ENV_PATH) -> dict[str, str]:
    values: dict[str, str] = {}
    if not env_path.exists():
        return values
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip('"').strip("'")
    return values


def write_env_updates(env_path: Path, updates: dict[str, str | None]) -> None:
    values = load_env_file(env_path)
    for key, value in updates.items():
        if value is None:
            values.pop(key, None)
            continue
        clean = str(value).strip()
        if not clean:
            values.pop(key, None)
            continue
        if "\n" in clean or "\r" in clean:
            raise ValueError(f"{key} must not contain newline characters")
        values[key] = clean
    env_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "\n".join(f"{key}={values[key]}" for key in sorted(values))
    env_path.write_text(rendered + ("\n" if rendered else ""), encoding="utf-8")


def load_yaml_config(config_path: Path = HERMES_CONFIG_PATH) -> dict[str, Any]:
    if not config_path.exists():
        return {}
    loaded = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    return loaded if isinstance(loaded, dict) else {}


def save_yaml_config(config_path: Path, config: dict[str, Any]) -> None:
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(config, sort_keys=False, allow_unicode=True), encoding="utf-8")


def mask_secret(value: str) -> str:
    if not value:
        return ""
    if len(value) <= 8:
        return "***"
    return value[:4] + "…" + value[-2:]


def extract_model_config(config: dict[str, Any]) -> dict[str, str]:
    model_cfg = config.get("model", {})
    if isinstance(model_cfg, str):
        return {"provider": "", "default": model_cfg, "base_url": ""}
    if not isinstance(model_cfg, dict):
        return {"provider": "", "default": "", "base_url": ""}
    return {
        "provider": str(model_cfg.get("provider") or "").strip(),
        "default": str(model_cfg.get("default") or "").strip(),
        "base_url": str(model_cfg.get("base_url") or "").strip(),
    }


def apply_provider_setup(
    *,
    config_path: Path,
    env_path: Path,
    provider: str,
    model: str,
    api_key: str,
    base_url: str = "",
) -> dict[str, str]:
    provider = (provider or "").strip().lower()
    if provider not in _SUPPORTED_PROVIDER_SETUPS:
        raise ValueError(f"Unsupported provider: {provider}")
    meta = _SUPPORTED_PROVIDER_SETUPS[provider]
    model = (model or meta["default_model"]).strip()
    base_url = (base_url or meta.get("default_base_url") or "").strip().rstrip("/")
    if meta.get("requires_base_url") and not base_url:
        raise ValueError("base_url is required for custom providers")
    if not model:
        raise ValueError("model is required")
    if not api_key:
        raise ValueError("api_key is required")

    config = load_yaml_config(config_path)
    model_cfg = config.get("model") if isinstance(config.get("model"), dict) else {}
    model_cfg = dict(model_cfg)
    model_cfg["provider"] = provider
    model_cfg["default"] = model
    if base_url:
        model_cfg["base_url"] = base_url
    else:
        model_cfg.pop("base_url", None)
    config["model"] = model_cfg
    save_yaml_config(config_path, config)
    write_env_updates(env_path, {meta["env_var"]: api_key})
    return {"provider": provider, "model": model, "env_var": meta["env_var"]}


def has_valid_channel_credentials(env_values: dict[str, str]) -> bool:
    telegram = env_values.get("TELEGRAM_BOT_TOKEN", "").strip()
    discord = env_values.get("DISCORD_BOT_TOKEN", "").strip()
    slack = env_values.get("SLACK_BOT_TOKEN", "").strip()
    whatsapp = env_values.get("WHATSAPP_ENABLED", "").strip().lower()
    email = env_values.get("EMAIL_ADDRESS", "").strip()
    return any([
        bool(telegram),
        bool(discord),
        bool(slack),
        whatsapp in {"1", "true", "yes", "on"},
        bool(email),
    ])


def has_valid_provider_setup(config: dict[str, Any], env_values: dict[str, str]) -> bool:
    model_cfg = extract_model_config(config)
    provider = model_cfg["provider"].lower()
    if provider in _SUPPORTED_PROVIDER_SETUPS:
        env_var = _SUPPORTED_PROVIDER_SETUPS[provider]["env_var"]
        return bool(model_cfg["default"] and env_values.get(env_var, "").strip())
    if provider:
        return bool(model_cfg["default"])
    return False


def should_autostart_gateway(
    *,
    config_path: Path = HERMES_CONFIG_PATH,
    env_path: Path = HERMES_ENV_PATH,
    autostart_mode: str | None = None,
) -> bool:
    mode = (autostart_mode or GATEWAY_AUTOSTART).strip().lower()
    if mode in {"0", "false", "no", "off", "disabled"}:
        return False
    config = load_yaml_config(config_path)
    env_values = load_env_file(env_path)
    channels_ready = has_valid_channel_credentials(env_values)
    providers_ready = has_valid_provider_setup(config, env_values)
    if mode in {"1", "true", "yes", "on", "enabled"}:
        return channels_ready and providers_ready
    return channels_ready and providers_ready


def save_channel_values(env_path: Path, updates: dict[str, str | None]) -> dict[str, str]:
    allowed = set(CHANNEL_ENV_KEYS) | GATEWAY_EXTRA_KEYS
    filtered = {key: value for key, value in updates.items() if key in allowed}
    write_env_updates(env_path, filtered)
    return load_env_file(env_path)


def masked_env_snapshot(env_values: dict[str, str]) -> dict[str, str]:
    masked: dict[str, str] = {}
    for key, value in env_values.items():
        if key in _PROVIDER_ENV_VARS or key in CHANNEL_ENV_KEYS or key.endswith("_PASSWORD") or key.endswith("_TOKEN"):
            masked[key] = mask_secret(value)
        else:
            masked[key] = value
    return masked


GATEWAY_EXTRA_KEYS = {"GATEWAY_ALLOW_ALL_USERS"}

_PLAINTEXT_CHANNEL_KEYS = {"TELEGRAM_ALLOWED_USERS", "DISCORD_ALLOWED_USERS", "GATEWAY_ALLOW_ALL_USERS"}


def channel_form_values(env_values: dict[str, str]) -> dict[str, str]:
    """Return channel env values safe to pre-populate form fields.
    Tokens/passwords are masked; user ID lists are returned plaintext."""
    result: dict[str, str] = {}
    for key in (*CHANNEL_ENV_KEYS, *GATEWAY_EXTRA_KEYS):
        value = env_values.get(key, "")
        if not value:
            result[key] = ""
        elif key in _PLAINTEXT_CHANNEL_KEYS:
            result[key] = value
        else:
            result[key] = mask_secret(value)
    return result


def channel_summary(env_values: dict[str, str]) -> list[dict[str, Any]]:
    summary = []
    for slug, meta in CHANNEL_FIELDS.items():
        primary = env_values.get(meta["primary"], "").strip()
        secondary = env_values.get(meta["secondary"], "").strip() if meta["secondary"] else ""
        enabled = False
        if slug == "whatsapp":
            enabled = primary.lower() in {"1", "true", "yes", "on"}
        else:
            enabled = bool(primary)
        summary.append({
            "slug": slug,
            "label": meta["label"],
            "enabled": enabled,
            "primary_key": meta["primary"],
            "secondary_key": meta["secondary"],
            "primary_value": mask_secret(primary),
            "secondary_value": mask_secret(secondary),
            "hint": meta["hint"],
        })
    return summary


def provider_catalog() -> list[dict[str, Any]]:
    return [
        {
            "id": key,
            "label": meta["label"],
            "env_var": meta["env_var"],
            "default_model": meta["default_model"],
            "requires_base_url": meta.get("requires_base_url", False),
            "default_base_url": meta.get("default_base_url", ""),
        }
        for key, meta in _SUPPORTED_PROVIDER_SETUPS.items()
    ]


_PAIRING_OLD = HERMES_HOME / "pairing"
_PAIRING_NEW = HERMES_HOME / "platforms" / "pairing"
CODE_TTL_SECONDS = 3600


def _pairing_dir() -> Path:
    """Resolve pairing directory — matches gateway's get_hermes_dir() logic."""
    if _PAIRING_OLD.exists():
        return _PAIRING_OLD
    return _PAIRING_NEW


def _load_pairing_json(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_pairing_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass


def pairing_platforms(suffix: str) -> list[str]:
    d = _pairing_dir()
    if not d.exists():
        return []
    return [
        f.stem.rsplit(f"-{suffix}", 1)[0]
        for f in d.glob(f"*-{suffix}.json")
    ]


def get_pending_pairings() -> list[dict[str, Any]]:
    now = time.time()
    results: list[dict[str, Any]] = []
    d = _pairing_dir()
    for platform in pairing_platforms("pending"):
        pending = _load_pairing_json(d / f"{platform}-pending.json")
        for code, info in pending.items():
            age = now - info.get("created_at", now)
            if age > CODE_TTL_SECONDS:
                continue
            results.append({
                "platform": platform,
                "code": code,
                "user_id": info.get("user_id", ""),
                "user_name": info.get("user_name", ""),
                "age_minutes": int(age / 60),
            })
    return results


def get_approved_users() -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    d = _pairing_dir()
    for platform in pairing_platforms("approved"):
        approved = _load_pairing_json(d / f"{platform}-approved.json")
        for user_id, info in approved.items():
            results.append({
                "platform": platform,
                "user_id": user_id,
                "user_name": info.get("user_name", ""),
                "approved_at": info.get("approved_at", 0),
            })
    return results


def approve_pairing(platform: str, code: str) -> dict[str, str]:
    d = _pairing_dir()
    pending_path = d / f"{platform}-pending.json"
    pending = _load_pairing_json(pending_path)
    if code not in pending:
        raise KeyError("Code not found or expired")
    entry = pending.pop(code)
    _save_pairing_json(pending_path, pending)
    approved_path = d / f"{platform}-approved.json"
    approved = _load_pairing_json(approved_path)
    approved[entry["user_id"]] = {
        "user_name": entry.get("user_name", ""),
        "approved_at": time.time(),
    }
    _save_pairing_json(approved_path, approved)
    return {"user_id": entry["user_id"], "user_name": entry.get("user_name", "")}


def deny_pairing(platform: str, code: str) -> None:
    pending_path = _pairing_dir() / f"{platform}-pending.json"
    pending = _load_pairing_json(pending_path)
    if code in pending:
        del pending[code]
        _save_pairing_json(pending_path, pending)


def revoke_user(platform: str, user_id: str) -> None:
    approved_path = _pairing_dir() / f"{platform}-approved.json"
    approved = _load_pairing_json(approved_path)
    if user_id in approved:
        del approved[user_id]
        _save_pairing_json(approved_path, approved)
