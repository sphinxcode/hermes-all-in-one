from pathlib import Path

from control_plane.config import deployment_metadata
from control_plane.server import app, health


def test_dashboard_routes_are_registered_before_webui_catchall():
    route_paths = [getattr(route, "path", "") for route in app.routes]

    assert "/dashboard" in route_paths
    assert "/dashboard/{path:path}" in route_paths
    assert "/dashboard-api/{path:path}" in route_paths
    assert route_paths.index("/dashboard") < route_paths.index("/{path:path}")


def test_health_payload_includes_dashboard_and_deployment_metadata():
    constants = health.__code__.co_consts

    assert "dashboard" in constants
    assert "deployment" in constants


def test_deployment_metadata_uses_railway_git_environment(monkeypatch):
    monkeypatch.setenv("RAILWAY_GIT_REPO_OWNER", "cch1rag")
    monkeypatch.setenv("RAILWAY_GIT_REPO_NAME", "hermes-all-in-one")
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "abc123")

    metadata = deployment_metadata()

    assert metadata["git_repo_owner"] == "cch1rag"
    assert metadata["git_repo_name"] == "hermes-all-in-one"
    assert metadata["git_commit_sha"] == "abc123"


def test_sync_workflow_pushes_to_checked_out_repository():
    workflow = Path(".github/workflows/sync-upstreams.yml").read_text(encoding="utf-8")

    assert "sphinxcode/hermes-all-in-one" not in workflow
    assert "GITHUB_REPOSITORY" in workflow
