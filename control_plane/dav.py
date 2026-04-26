from __future__ import annotations

import base64
from typing import Callable

from wsgidav.fs_dav_provider import FilesystemProvider
from wsgidav.wsgidav_app import WsgiDAVApp

from control_plane.auth import admin_auth_enabled, verify_admin_password
from control_plane.config import DATA_DIR


def _require_basic_auth(app: Callable) -> Callable:
    def middleware(environ: dict, start_response: Callable) -> object:
        if admin_auth_enabled():
            auth = environ.get("HTTP_AUTHORIZATION", "")
            password = ""
            if auth.startswith("Basic "):
                try:
                    decoded = base64.b64decode(auth[6:]).decode("utf-8", errors="ignore")
                    password = decoded.split(":", 1)[1] if ":" in decoded else ""
                except Exception:
                    pass
            if not verify_admin_password(password):
                start_response(
                    "401 Unauthorized",
                    [
                        ("WWW-Authenticate", 'Basic realm="Hermes Files"'),
                        ("Content-Type", "text/plain"),
                    ],
                )
                return [b"Authentication required"]
        return app(environ, start_response)

    return middleware


def build_dav_app() -> Callable:
    config = {
        "provider_mapping": {"/": FilesystemProvider(str(DATA_DIR))},
        "http_authenticator": {"domain_controller": None},
        "simple_dc": {"user_mapping": {}},
        "verbose": 0,
        "logging": {"enable_loggers": []},
    }
    return _require_basic_auth(WsgiDAVApp(config))
