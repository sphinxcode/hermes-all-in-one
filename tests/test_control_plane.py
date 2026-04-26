from pathlib import Path

import pytest
import yaml

from control_plane.auth import create_admin_session, verify_admin_session
from control_plane.config import (
    _SUPPORTED_PROVIDER_SETUPS,
    apply_provider_setup,
    has_valid_channel_credentials,
    load_env_file,
    should_autostart_gateway,
    write_env_updates,
)
from control_plane.server import dashboard_update_not_supported_status


def test_write_env_updates_round_trips_values(tmp_path: Path):
    env_path = tmp_path / ".env"

    write_env_updates(env_path, {"OPENROUTER_API_KEY": "sk-test", "TELEGRAM_BOT_TOKEN": "123:abc"})

    values = load_env_file(env_path)
    assert values["OPENROUTER_API_KEY"] == "sk-test"
    assert values["TELEGRAM_BOT_TOKEN"] == "123:abc"


def test_apply_provider_setup_writes_yaml_and_env(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"

    result = apply_provider_setup(
        config_path=config_path,
        env_path=env_path,
        provider="openrouter",
        model="anthropic/claude-sonnet-4.6",
        api_key="sk-or-test",
        base_url="",
    )

    config = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    values = load_env_file(env_path)

    assert result["provider"] == "openrouter"
    assert config["model"]["provider"] == "openrouter"
    assert config["model"]["default"] == "anthropic/claude-sonnet-4.6"
    assert values["OPENROUTER_API_KEY"] == "sk-or-test"


def test_apply_provider_setup_requires_base_url_for_custom(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"

    with pytest.raises(ValueError, match="base_url"):
        apply_provider_setup(
            config_path=config_path,
            env_path=env_path,
            provider="custom",
            model="gpt-4o-mini",
            api_key="sk-test",
            base_url="",
        )


def test_supported_provider_catalog_exposes_api_key_happy_path():
    assert "openrouter" in _SUPPORTED_PROVIDER_SETUPS
    assert _SUPPORTED_PROVIDER_SETUPS["openrouter"]["env_var"] == "OPENROUTER_API_KEY"
    assert _SUPPORTED_PROVIDER_SETUPS["custom"]["requires_base_url"] is True


def test_has_valid_channel_credentials_prefers_real_channel_tokens():
    assert has_valid_channel_credentials({"TELEGRAM_BOT_TOKEN": "123:abc"}) is True
    assert has_valid_channel_credentials({"DISCORD_BOT_TOKEN": "discord-token"}) is True
    assert has_valid_channel_credentials({"WHATSAPP_ENABLED": "1"}) is True
    assert has_valid_channel_credentials({"OPENROUTER_API_KEY": "sk-only"}) is False


def test_should_autostart_gateway_requires_provider_and_channel(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    env_path = tmp_path / ".env"

    config_path.write_text(yaml.safe_dump({"model": {"provider": "openrouter", "default": "anthropic/claude-sonnet-4.6"}}), encoding="utf-8")
    write_env_updates(env_path, {"OPENROUTER_API_KEY": "sk-or-test"})
    assert should_autostart_gateway(config_path=config_path, env_path=env_path) is False

    write_env_updates(env_path, {"TELEGRAM_BOT_TOKEN": "123:abc"})
    assert should_autostart_gateway(config_path=config_path, env_path=env_path) is True


def test_admin_session_round_trip():
    cookie = create_admin_session()
    assert verify_admin_session(cookie) is True


def test_dashboard_update_status_explains_container_redeploy_path():
    status = dashboard_update_not_supported_status()

    assert status["name"] == "hermes-update"
    assert status["running"] is False
    assert status["exit_code"] == 1
    assert any("Railway/container image" in line for line in status["lines"])
