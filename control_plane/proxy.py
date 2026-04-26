from __future__ import annotations

from collections.abc import Mapping

import httpx
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import Response, StreamingResponse

from control_plane.config import (
    INTERNAL_DASHBOARD_BASE,
    INTERNAL_DASHBOARD_HOST,
    INTERNAL_DASHBOARD_PORT,
    INTERNAL_WEBUI_BASE,
)

_HOP_BY_HOP = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-length",
}


def _rewrite_dashboard_location(location: str | None) -> str | None:
    if not location or not location.startswith("/"):
        return location
    if location == "/":
        return "/dashboard"
    if location == "/api" or location.startswith("/api/"):
        return "/dashboard-api" + location[4:]
    if location.startswith("/assets/"):
        return "/dashboard-assets" + location[7:]
    if location.startswith("/dashboard-plugins/"):
        return location
    if location.startswith("/dashboard"):
        return location
    return "/dashboard" + location


def _dashboard_response_headers(headers: dict[str, str]) -> dict[str, str]:
    rewritten = dict(headers)
    location = rewritten.get("location")
    if location:
        rewritten["location"] = _rewrite_dashboard_location(location) or location
    return rewritten


def _dashboard_request_headers(headers_in: Mapping[str, str]) -> dict[str, str]:
    headers = {}
    for key, value in headers_in.items():
        lower = key.lower()
        if lower in _HOP_BY_HOP or lower == "host":
            continue
        headers[key] = value
    # Dashboard enforces Host header checks. Always present the internal host.
    headers["Host"] = f"{INTERNAL_DASHBOARD_HOST}:{INTERNAL_DASHBOARD_PORT}"
    return headers


async def proxy_to_webui(request: Request, path: str) -> Response:
    upstream_path = "/" + path.lstrip("/")
    target_url = f"{INTERNAL_WEBUI_BASE}{upstream_path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = {}
    for key, value in request.headers.items():
        lower = key.lower()
        if lower in _HOP_BY_HOP:
            continue
        headers[key] = value
    headers["X-Forwarded-Host"] = request.headers.get("host", "")
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Real-Host"] = request.headers.get("host", "")

    body = await request.body()
    client = httpx.AsyncClient(follow_redirects=False, timeout=60.0)
    upstream_request = client.build_request(
        request.method,
        target_url,
        headers=headers,
        content=body if body else None,
    )
    upstream_response = await client.send(upstream_request, stream=True)
    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in _HOP_BY_HOP
    }

    async def _close_upstream() -> None:
        await upstream_response.aclose()
        await client.aclose()

    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=response_headers,
        background=BackgroundTask(_close_upstream),
    )


def _rewrite_dashboard_html(html: str) -> str:
    # Route dashboard static + API traffic through control-plane prefixes.
    html = html.replace('"/assets/', '"/dashboard-assets/')
    html = html.replace("'/assets/", "'/dashboard-assets/")

    patch_script = """
<script>
(() => {
  const ORIGINAL_FETCH = window.fetch?.bind(window);
  if (!ORIGINAL_FETCH) return;
  function rewrite(url) {
    if (typeof url === "string") {
      if (url.startsWith("/api/")) return `/dashboard-api/${url.slice(5)}`;
      if (url === "/api") return "/dashboard-api";
      return url;
    }
    if (url instanceof URL && url.origin === window.location.origin) {
      if (url.pathname.startsWith("/api/")) {
        url.pathname = `/dashboard-api/${url.pathname.slice(5)}`;
      } else if (url.pathname === "/api") {
        url.pathname = "/dashboard-api";
      }
    }
    return url;
  }
  window.fetch = (input, init) => ORIGINAL_FETCH(rewrite(input), init);
})();
</script>
"""
    return html.replace("</head>", f"{patch_script}</head>", 1)


async def proxy_to_dashboard(
    request: Request,
    upstream_path: str,
    *,
    rewrite_html: bool = False,
) -> Response:
    path = "/" + upstream_path.lstrip("/")
    target_url = f"{INTERNAL_DASHBOARD_BASE}{path}"
    if request.url.query:
        target_url = f"{target_url}?{request.url.query}"

    headers = _dashboard_request_headers(request.headers)
    headers["X-Forwarded-Host"] = request.headers.get("host", "")
    headers["X-Forwarded-Proto"] = request.url.scheme
    headers["X-Real-Host"] = request.headers.get("host", "")

    body = await request.body()

    if rewrite_html:
        async with httpx.AsyncClient(follow_redirects=False, timeout=60.0) as client:
            upstream_response = await client.request(
                request.method,
                target_url,
                headers=headers,
                content=body if body else None,
            )
            response_headers = {
                key: value
                for key, value in upstream_response.headers.items()
                if key.lower() not in _HOP_BY_HOP
            }
            response_headers = _dashboard_response_headers(response_headers)
            content_type = upstream_response.headers.get("content-type", "").lower()
            if "text/html" in content_type:
                html = upstream_response.text
                html = _rewrite_dashboard_html(html)
                response_headers.pop("content-length", None)
                return Response(
                    content=html.encode("utf-8"),
                    status_code=upstream_response.status_code,
                    headers=response_headers,
                    media_type="text/html; charset=utf-8",
                )
            return Response(
                content=upstream_response.content,
                status_code=upstream_response.status_code,
                headers=response_headers,
            )

    client = httpx.AsyncClient(follow_redirects=False, timeout=60.0)
    upstream_request = client.build_request(
        request.method,
        target_url,
        headers=headers,
        content=body if body else None,
    )
    upstream_response = await client.send(upstream_request, stream=True)
    response_headers = {
        key: value
        for key, value in upstream_response.headers.items()
        if key.lower() not in _HOP_BY_HOP
    }
    response_headers = _dashboard_response_headers(response_headers)

    async def _close_upstream() -> None:
        await upstream_response.aclose()
        await client.aclose()

    return StreamingResponse(
        upstream_response.aiter_raw(),
        status_code=upstream_response.status_code,
        headers=response_headers,
        background=BackgroundTask(_close_upstream),
    )
