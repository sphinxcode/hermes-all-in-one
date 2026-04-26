from __future__ import annotations

from typing import Callable

from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.wsgidav_app import WsgiDAVApp

from control_plane.auth import admin_auth_enabled
from control_plane.config import ADMIN_PASSWORD, DATA_DIR, WEBUI_AGENT_DIR

_DAV_USERNAME = "admin"


def build_dav_app() -> Callable:
    provider_mapping: dict = {"/": FilesystemProvider(str(DATA_DIR))}
    if WEBUI_AGENT_DIR.exists():
        provider_mapping["/vendor/hermes-agent"] = FilesystemProvider(str(WEBUI_AGENT_DIR))

    config: dict = {
        "provider_mapping": provider_mapping,
        "verbose": 0,
        "logging": {"enable_loggers": []},
    }

    if admin_auth_enabled():
        config["http_authenticator"] = {
            "domain_controller": "wsgidav.dc.simple_dc.SimpleDomainController",
            "accept_basic": True,
            "accept_digest": False,
            "default_to_digest": False,
        }
        config["simple_dc"] = {
            "user_mapping": {"*": {_DAV_USERNAME: {"password": ADMIN_PASSWORD}}}
        }
    else:
        config["http_authenticator"] = {
            "domain_controller": "wsgidav.dc.simple_dc.SimpleDomainController",
            "accept_basic": True,
            "accept_digest": False,
            "default_to_digest": False,
        }
        config["simple_dc"] = {"user_mapping": {"*": True}}

    return WsgiDAVApp(config)
