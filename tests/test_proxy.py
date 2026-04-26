from control_plane.proxy import _rewrite_dashboard_location


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
