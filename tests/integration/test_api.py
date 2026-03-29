import os

from fastapi.testclient import TestClient


def test_dashboard_and_core_api_routes_smoke() -> None:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    from app.main import app

    with TestClient(app) as client:
        health = client.get("/health")
        dashboard = client.get("/")
        opportunities = client.get("/opportunities")

        assert health.status_code == 200
        assert dashboard.status_code == 200
        assert opportunities.status_code == 200
