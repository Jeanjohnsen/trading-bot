import os

from fastapi.testclient import TestClient


def test_dashboard_and_core_api_routes_smoke() -> None:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from app.main import app

    with TestClient(app) as client:
        health = client.get("/health")
        dashboard = client.get("/")
        opportunities = client.get("/opportunities")
        mode_change = client.post("/settings/app-mode", json={"mode": "backtest"})
        claude_toggle = client.post("/settings/claude-agent", json={"enabled": False})
        updated_health = client.get("/health")
        updated_settings = client.get("/settings")

        assert health.status_code == 200
        assert dashboard.status_code == 200
        assert opportunities.status_code == 200
        assert mode_change.status_code == 200
        assert claude_toggle.status_code == 200
        assert mode_change.json()["mode"] == "backtest"
        assert updated_health.json()["mode"] == "backtest"
        assert updated_health.json()["claude"]["operator_enabled"] is False
        assert updated_settings.json()["claude"]["operator_enabled"] is False
