from __future__ import annotations

import hashlib
import hmac
import secrets
import time
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse, RedirectResponse, Response

from control_plane.config import (
    ADMIN_COOKIE_NAME,
    ADMIN_PASSWORD,
    ADMIN_SESSION_TTL,
    DATA_DIR,
)

_SESSIONS: dict[str, float] = {}
_SIGNING_KEY_PATH = DATA_DIR / ".admin_signing_key"
_EPHEMERAL_SIGNING_KEY: bytes | None = None


def _signing_key() -> bytes:
    global _EPHEMERAL_SIGNING_KEY
    if _SIGNING_KEY_PATH.exists():
        raw = _SIGNING_KEY_PATH.read_bytes()
        if len(raw) >= 32:
            return raw[:32]
    key = secrets.token_bytes(32)
    try:
        _SIGNING_KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
        _SIGNING_KEY_PATH.write_bytes(key)
        try:
            _SIGNING_KEY_PATH.chmod(0o600)
        except OSError:
            pass
        return key
    except OSError:
        if _EPHEMERAL_SIGNING_KEY is None:
            _EPHEMERAL_SIGNING_KEY = key
        return _EPHEMERAL_SIGNING_KEY


def admin_auth_enabled() -> bool:
    return bool(ADMIN_PASSWORD)


def verify_admin_password(password: str) -> bool:
    if not admin_auth_enabled():
        return True
    return hmac.compare_digest(password or "", ADMIN_PASSWORD)


def _prune_sessions() -> None:
    now = time.time()
    for token, expiry in list(_SESSIONS.items()):
        if expiry <= now:
            _SESSIONS.pop(token, None)


def create_admin_session() -> str:
    token = secrets.token_hex(32)
    _SESSIONS[token] = time.time() + ADMIN_SESSION_TTL
    sig = hmac.new(_signing_key(), token.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{token}.{sig}"


def verify_admin_session(cookie_value: str | None) -> bool:
    if not cookie_value or "." not in cookie_value:
        return False
    _prune_sessions()
    token, sig = cookie_value.rsplit(".", 1)
    expected = hmac.new(_signing_key(), token.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(sig, expected):
        return False
    expiry = _SESSIONS.get(token)
    if not expiry or expiry <= time.time():
        _SESSIONS.pop(token, None)
        return False
    return True


def clear_admin_session(cookie_value: str | None) -> None:
    if cookie_value and "." in cookie_value:
        token = cookie_value.rsplit(".", 1)[0]
        _SESSIONS.pop(token, None)


def admin_cookie_value(request: Request) -> str | None:
    return request.cookies.get(ADMIN_COOKIE_NAME)


def is_admin_authenticated(request: Request) -> bool:
    if not admin_auth_enabled():
        return True
    return verify_admin_session(admin_cookie_value(request))


def set_admin_cookie(response: Response, cookie_value: str) -> None:
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        cookie_value,
        httponly=True,
        samesite="lax",
        max_age=ADMIN_SESSION_TTL,
        secure=request_is_secure(response.headers.get("x-forwarded-proto")),
        path="/",
    )


def clear_admin_cookie(response: Response) -> None:
    response.delete_cookie(ADMIN_COOKIE_NAME, path="/")


def request_is_secure(proto_header: str | None) -> bool:
    return (proto_header or "").lower() == "https"


def admin_unauthorized_response(request: Request) -> Response:
    if request.url.path.startswith(("/admin/api/", "/dashboard-api")):
        return JSONResponse({"error": "Authentication required"}, status_code=401)
    return RedirectResponse(url="/admin/login", status_code=302)
