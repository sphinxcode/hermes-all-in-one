from starlette.datastructures import Headers

from control_plane.proxy import _dashboard_request_headers, _rewrite_dashboard_location


def test_rewrite_dashboard_location_for_api_paths():
    assert _rewrite_dashboard_location("/api") == "/dashboard-api"
    assert _rewrite_dashboard_location("/api/status") == "/dashboard-api/status"


def test_rewrite_dashboard_location_for_static_paths():
    assert _rewrite_dashboard_location("/assets/main.js") == "/dashboard-assets/main.js"
    assert _rewrite_dashboard_location("/dashboard-plugins/healthz") == "/dashboard-plugins/healthz"


def test_rewrite_dashboard_location_for_app_routes():
    assert _rewrite_dashboard_location("/") == "/dashboard"
    assert _rewrite_dashboard_location("/login") == "/dashboard/login"
    assert _rewrite_dashboard_location("/dashboard/settings") == "/dashboard/settings"


def test_rewrite_dashboard_location_keeps_external_urls():
    assert _rewrite_dashboard_location("https://example.com/login") == "https://example.com/login"
    assert _rewrite_dashboard_location(None) is None


def test_dashboard_request_headers_replace_incoming_host():
    headers = _dashboard_request_headers(
        Headers(
            raw=[
                (b"host", b"hermes-all-in-one-production-2493.up.railway.app"),
                (b"x-forwarded-proto", b"https"),
                (b"connection", b"keep-alive"),
            ]
        )
    )

    host_headers = [key for key in headers if key.lower() == "host"]
    assert host_headers == ["Host"]
    assert headers["Host"] == "127.0.0.1:9119"
    assert headers["x-forwarded-proto"] == "https"
    assert "connection" not in {key.lower() for key in headers}
