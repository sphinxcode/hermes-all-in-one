from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from pathlib import Path

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles
from starlette.templating import Jinja2Templates

from control_plane.auth import (
    ADMIN_COOKIE_NAME,
    admin_auth_enabled,
    admin_cookie_value,
    admin_unauthorized_response,
    clear_admin_cookie,
    clear_admin_session,
    create_admin_session,
    is_admin_authenticated,
    verify_admin_password,
)
from control_plane.config import (
    ADMIN_PASSWORD,
    CHANNEL_ENV_KEYS,
    HERMES_CONFIG_PATH,
    HERMES_ENV_PATH,
    STATUS_CACHE_TTL,
    UNSUPPORTED_PROVIDER_NOTE,
    WEBUI_STATE_DIR,
    WORKSPACE_DIR,
    apply_provider_setup,
    approve_pairing,
    channel_form_values,
    channel_summary,
    deployment_metadata,
    deny_pairing,
    ensure_runtime_dirs,
    extract_model_config,
    get_approved_users,
    get_pending_pairings,
    load_env_file,
    load_yaml_config,
    masked_env_snapshot,
    provider_catalog,
    revoke_user,
    save_channel_values,
)
from control_plane.dashboard_manager import DashboardManager
from control_plane.gateway_manager import GatewayManager
from control_plane.proxy import proxy_to_dashboard, proxy_to_webui
from control_plane.webui_manager import WebUIManager

BASE_DIR = Path(__file__).resolve().parent
TEMPLATES = Jinja2Templates(directory=str(BASE_DIR / "templates"))

webui_manager = WebUIManager()
dashboard_manager = DashboardManager()
gateway_manager = GatewayManager()
_status_cache: dict[str, object] = {"ts": 0.0, "data": None}


def dashboard_update_not_supported_status() -> dict[str, object]:
    return {
        "name": "hermes-update",
        "running": False,
        "exit_code": 1,
        "pid": None,
        "lines": [
            "Hermes Agent updates are managed by the Railway/container image in this deployment.",
            "",
            "The dashboard's built-in update action expects /app/vendor/hermes-agent to be a writable Git checkout.",
            "This all-in-one image bakes the vendored agent into the container, so in-place `hermes update` would be lost on the next deploy.",
            "",
            "To update Hermes Agent here, sync the vendored upstream locally, rebuild the image, and redeploy.",
        ],
    }


def _invalidate_status_cache() -> None:
    _status_cache["ts"] = 0.0
    _status_cache["data"] = None


def _current_status() -> dict:
    now = time.time()
    if _status_cache["data"] and (now - float(_status_cache["ts"])) < STATUS_CACHE_TTL:
        return _status_cache["data"]  # type: ignore[return-value]

    env_values = load_env_file(HERMES_ENV_PATH)
    config = load_yaml_config(HERMES_CONFIG_PATH)
    data = {
        "webui": webui_manager.status(),
        "dashboard": dashboard_manager.status(),
        "gateway": gateway_manager.status(),
        "model": extract_model_config(config),
        "channels": channel_summary(env_values),
        "env_masked": masked_env_snapshot(env_values),
        "autostart": gateway_manager.should_autostart(),
        "provider_catalog": provider_catalog(),
        "unsupported_provider_note": UNSUPPORTED_PROVIDER_NOTE,
        "deployment": deployment_metadata(),
        "paths": {
            "hermes_home": str(HERMES_CONFIG_PATH.parent),
            "config_path": str(HERMES_CONFIG_PATH),
            "env_path": str(HERMES_ENV_PATH),
            "webui_state_dir": str(WEBUI_STATE_DIR),
            "workspace_dir": str(WORKSPACE_DIR),
        },
    }
    _status_cache["ts"] = now
    _status_cache["data"] = data
    return data


def _admin_required(request: Request) -> Response | None:
    if is_admin_authenticated(request):
        return None
    return admin_unauthorized_response(request)


async def on_startup() -> None:
    ensure_runtime_dirs()
    webui_manager.start()
    webui_manager.wait_until_ready(timeout=30)
    dashboard_manager.start()
    dashboard_manager.wait_until_ready(timeout=30)
    if gateway_manager.should_autostart():
        gateway_manager.start()
    _invalidate_status_cache()


async def on_shutdown() -> None:
    gateway_manager.stop()
    dashboard_manager.stop()
    webui_manager.stop()


async def health(request: Request) -> JSONResponse:
    status = _current_status()
    webui_ok = bool(status["webui"]["healthy"])
    dashboard_ok = bool(status["dashboard"]["healthy"])
    all_ok = webui_ok and dashboard_ok
    payload = {
        "status": "ok" if all_ok else "degraded",
        "service": "hermes-control-plane",
        "webui": status["webui"],
        "dashboard": status["dashboard"],
        "deployment": status["deployment"],
        "gateway": {
            "running": status["gateway"]["running"],
            "healthy": status["gateway"]["healthy"],
        },
    }
    return JSONResponse(payload, status_code=200 if all_ok else 503)


async def admin_login_page(request: Request) -> HTMLResponse:
    if is_admin_authenticated(request):
        return RedirectResponse(url="/admin", status_code=302)
    html = """
    <!doctype html>
    <html lang=\"en\"><head><meta charset=\"utf-8\"><meta name=\"viewport\" content=\"width=device-width, initial-scale=1\"><title>Hermes Admin Login</title>
    <style>
    body{font-family:Inter,system-ui,sans-serif;background:#0f172a;color:#e5e7eb;display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}
    form{background:#111827;border:1px solid #1f2937;border-radius:16px;padding:32px;min-width:320px;box-shadow:0 24px 80px rgba(0,0,0,.35)}
    h1{margin:0 0 8px;font-size:24px}p{margin:0 0 24px;color:#94a3b8}input{width:100%;padding:12px 14px;border-radius:12px;border:1px solid #334155;background:#020617;color:#e5e7eb;box-sizing:border-box}button{margin-top:16px;width:100%;padding:12px 14px;border:0;border-radius:12px;background:#2563eb;color:#fff;font-weight:600}small{display:block;margin-top:16px;color:#64748b}
    </style></head><body><form method=\"post\" action=\"/admin/login\"><h1>Hermes Admin</h1><p>Control plane access for your Railway deployment.</p><input type=\"password\" name=\"password\" placeholder=\"Admin password\" autofocus required><button type=\"submit\">Sign in</button><small>Set HERMES_ADMIN_PASSWORD for a dedicated admin password. If omitted, Hermes falls back to HERMES_WEBUI_PASSWORD.</small></form></body></html>
    """
    return HTMLResponse(html)


async def admin_login(request: Request) -> Response:
    from urllib.parse import parse_qs

    raw = (await request.body()).decode("utf-8", errors="ignore")
    form = {key: values[-1] for key, values in parse_qs(raw, keep_blank_values=True).items()}
    password = str(form.get("password") or "")
    if not verify_admin_password(password):
        return HTMLResponse("Invalid password", status_code=401)
    response = RedirectResponse(url="/admin", status_code=302)
    response.set_cookie(
        ADMIN_COOKIE_NAME,
        create_admin_session(),
        httponly=True,
        samesite="lax",
        max_age=24 * 60 * 60,
        secure=request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https",
        path="/",
    )
    return response


async def admin_logout(request: Request) -> Response:
    clear_admin_session(admin_cookie_value(request))
    response = RedirectResponse(url="/admin/login", status_code=302)
    clear_admin_cookie(response)
    return response


async def admin_index(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    status = _current_status()
    return TEMPLATES.TemplateResponse(
        request,
        "admin.html",
        {
            "status": status,
            "provider_catalog": provider_catalog(),
            "unsupported_provider_note": UNSUPPORTED_PROVIDER_NOTE,
            "admin_auth_enabled": admin_auth_enabled(),
            "has_separate_admin_password": bool(ADMIN_PASSWORD),
        },
    )


async def api_status(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    return JSONResponse(_current_status())


async def api_gateway_action(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    action = request.path_params["action"]
    if action == "start":
        gateway_manager.start()
    elif action == "stop":
        gateway_manager.stop()
    elif action == "restart":
        gateway_manager.restart()
    else:
        return JSONResponse({"error": "unknown action"}, status_code=400)
    _invalidate_status_cache()
    return JSONResponse({"ok": True, "status": _current_status()})


async def api_provider_setup(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    body = await request.json()
    result = apply_provider_setup(
        config_path=HERMES_CONFIG_PATH,
        env_path=HERMES_ENV_PATH,
        provider=str(body.get("provider") or ""),
        model=str(body.get("model") or ""),
        api_key=str(body.get("api_key") or ""),
        base_url=str(body.get("base_url") or ""),
    )
    _invalidate_status_cache()
    if gateway_manager.is_running():
        gateway_manager.restart()
    elif gateway_manager.should_autostart():
        gateway_manager.start()
    return JSONResponse({"ok": True, "result": result, "status": _current_status()})


async def api_channel_values(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    env_values = load_env_file(HERMES_ENV_PATH)
    return JSONResponse({"ok": True, "values": channel_form_values(env_values)})


async def api_channel_save(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    body = await request.json()
    all_keys = set(CHANNEL_ENV_KEYS) | {"GATEWAY_ALLOW_ALL_USERS"}
    updates = {key: body.get(key) for key in all_keys if key in body}
    if "TELEGRAM_BOT_TOKEN" in updates:
        updates.setdefault("TELEGRAM_ALLOWED_USERS", None)
    if "DISCORD_BOT_TOKEN" in updates:
        updates.setdefault("DISCORD_ALLOWED_USERS", None)
    env_values = save_channel_values(HERMES_ENV_PATH, updates)
    _invalidate_status_cache()
    restarted = False
    if gateway_manager.is_running():
        gateway_manager.restart()
        restarted = True
    elif gateway_manager.should_autostart():
        gateway_manager.start()
        restarted = True
    return JSONResponse({"ok": True, "restarted": restarted, "channels": channel_summary(env_values), "status": _current_status()})


async def api_webui_action(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    action = request.path_params["action"]
    if action == "restart":
        webui_manager.restart()
        webui_manager.wait_until_ready(timeout=30)
    else:
        return JSONResponse({"error": "unknown action"}, status_code=400)
    _invalidate_status_cache()
    return JSONResponse({"ok": True, "status": webui_manager.status()})


async def api_dashboard_action(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    action = request.path_params["action"]
    if action == "restart":
        dashboard_manager.restart()
        dashboard_manager.wait_until_ready(timeout=30)
    else:
        return JSONResponse({"error": "unknown action"}, status_code=400)
    _invalidate_status_cache()
    return JSONResponse({"ok": True, "status": dashboard_manager.status()})


async def dashboard_update_not_supported(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    return JSONResponse({"ok": True, "pid": None, "name": "hermes-update"})


async def dashboard_update_status(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    return JSONResponse(dashboard_update_not_supported_status())


async def api_pairing_pending(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    return JSONResponse({"ok": True, "pending": get_pending_pairings()})


async def api_pairing_approved(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    return JSONResponse({"ok": True, "approved": get_approved_users()})


async def api_pairing_approve(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    body = await request.json()
    platform = str(body.get("platform", "")).strip()
    code = str(body.get("code", "")).upper().strip()
    if not platform or not code:
        return JSONResponse({"error": "platform and code required"}, status_code=400)
    try:
        result = approve_pairing(platform, code)
    except KeyError:
        return JSONResponse({"error": "Code not found or expired"}, status_code=404)
    return JSONResponse({"ok": True, **result})


async def api_pairing_deny(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    body = await request.json()
    platform = str(body.get("platform", "")).strip()
    code = str(body.get("code", "")).upper().strip()
    if not platform or not code:
        return JSONResponse({"error": "platform and code required"}, status_code=400)
    deny_pairing(platform, code)
    return JSONResponse({"ok": True})


async def api_pairing_revoke(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    body = await request.json()
    platform = str(body.get("platform", "")).strip()
    user_id = str(body.get("user_id", "")).strip()
    if not platform or not user_id:
        return JSONResponse({"error": "platform and user_id required"}, status_code=400)
    revoke_user(platform, user_id)
    return JSONResponse({"ok": True})


async def proxy_catchall(request: Request) -> Response:
    path = request.path_params.get("path", "")
    return await proxy_to_webui(request, path)


async def proxy_dashboard_app(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    path = request.path_params.get("path", "")
    return await proxy_to_dashboard(request, path, rewrite_html=True)


async def proxy_dashboard_api(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    path = request.path_params.get("path", "")
    return await proxy_to_dashboard(request, f"api/{path}")


async def proxy_dashboard_assets(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    path = request.path_params.get("path", "")
    return await proxy_to_dashboard(request, f"assets/{path}")


async def proxy_dashboard_plugins(request: Request) -> Response:
    unauthorized = _admin_required(request)
    if unauthorized:
        return unauthorized
    path = request.path_params.get("path", "")
    return await proxy_to_dashboard(request, f"dashboard-plugins/{path}")


routes = [
    Route("/health", health),
    Route("/admin", admin_index),
    Route("/admin/login", admin_login_page, methods=["GET"]),
    Route("/admin/login", admin_login, methods=["POST"]),
    Route("/admin/logout", admin_logout, methods=["POST"]),
    Route("/admin/api/status", api_status),
    Route("/admin/api/gateway/{action}", api_gateway_action, methods=["POST"]),
    Route("/admin/api/provider/setup", api_provider_setup, methods=["POST"]),
    Route("/admin/api/channels", api_channel_values, methods=["GET"]),
    Route("/admin/api/channels/save", api_channel_save, methods=["POST"]),
    Route("/admin/api/webui/{action}", api_webui_action, methods=["POST"]),
    Route("/admin/api/dashboard/{action}", api_dashboard_action, methods=["POST"]),
    Route("/admin/api/pairing/pending", api_pairing_pending),
    Route("/admin/api/pairing/approved", api_pairing_approved),
    Route("/admin/api/pairing/approve", api_pairing_approve, methods=["POST"]),
    Route("/admin/api/pairing/deny", api_pairing_deny, methods=["POST"]),
    Route("/admin/api/pairing/revoke", api_pairing_revoke, methods=["POST"]),
    Mount("/admin/static", app=StaticFiles(directory=str(BASE_DIR / "static")), name="admin-static"),
    Route("/dashboard", proxy_dashboard_app, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
    Route("/dashboard/{path:path}", proxy_dashboard_app, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
    Route("/dashboard-api/hermes/update", dashboard_update_not_supported, methods=["POST"]),
    Route("/dashboard-api/actions/hermes-update/status", dashboard_update_status, methods=["GET"]),
    Route("/dashboard-api", proxy_dashboard_api, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
    Route("/dashboard-api/{path:path}", proxy_dashboard_api, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
    Route("/dashboard-assets/{path:path}", proxy_dashboard_assets, methods=["GET", "OPTIONS", "HEAD"]),
    Route("/dashboard-plugins/{path:path}", proxy_dashboard_plugins, methods=["GET", "OPTIONS", "HEAD"]),
    Route("/", proxy_catchall, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
    Route("/{path:path}", proxy_catchall, methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "HEAD"]),
]


@asynccontextmanager
async def lifespan(app: Starlette):
    await on_startup()
    try:
        yield
    finally:
        await on_shutdown()


app = Starlette(routes=routes, lifespan=lifespan)
