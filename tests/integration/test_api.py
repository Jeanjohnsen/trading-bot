import os

from fastapi.testclient import TestClient
from app.core.settings import get_settings


def test_dashboard_and_core_api_routes_smoke() -> None:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["ENABLE_RESEARCH_MODE"] = "true"
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as client:
        health = client.get("/health")
        dashboard = client.get("/")
        opportunities = client.get("/opportunities")
        risk = client.get("/risk")
        mode_change = client.post("/settings/app-mode", json={"mode": "backtest"})
        claude_toggle = client.post("/settings/claude-agent", json={"enabled": False})
        live_toggle = client.post("/settings/live-trading", json={"enabled": True})
        research_toggle = client.post("/settings/research-mode", json={"enabled": True})
        market_orders_toggle = client.post("/settings/market-orders", json={"enabled": True})
        trade_size = client.post("/settings/trade-size", json={"mode": "fixed", "fraction": 0.02})
        updated_health = client.get("/health")
        updated_settings = client.get("/settings")
        analytics = client.get("/analytics")

        assert health.status_code == 200
        assert dashboard.status_code == 200
        assert opportunities.status_code == 200
        assert risk.status_code == 200
        assert mode_change.status_code == 200
        assert claude_toggle.status_code == 200
        assert live_toggle.status_code == 200
        assert research_toggle.status_code == 200
        assert market_orders_toggle.status_code == 200
        assert trade_size.status_code == 200
        assert mode_change.json()["mode"] == "backtest"
        assert updated_health.json()["mode"] == "backtest"
        assert updated_health.json()["claude"]["operator_enabled"] is False
        assert "account" in risk.json()
        assert "account" in updated_health.json()
        assert "account" in updated_settings.json()
        assert updated_settings.json()["app"]["enable_live_trading"] is True
        assert updated_settings.json()["app"]["enable_research_mode"] is True
        assert updated_settings.json()["app"]["enable_market_orders"] is True
        assert updated_settings.json()["claude"]["operator_enabled"] is False
        assert updated_settings.json()["trade_sizing"]["global"]["fraction"] == 0.02
        assert analytics.json()["forecasting"]["tracked_markets"] > 0
        assert analytics.json()["forecasting"]["logged_snapshots"] > 0

        opportunity_payload = client.get("/opportunities").json()
        if opportunity_payload:
            override = client.post(
                f"/opportunities/{opportunity_payload[0]['opportunity_id']}/trade-size",
                json={"mode": "fixed", "fraction": 0.05},
            )
            assert override.status_code == 200


def test_execute_route_surfaces_runtime_errors(monkeypatch) -> None:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["ENABLE_RESEARCH_MODE"] = "true"
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as client:
        async def fail_execute(opportunity_id: str):  # noqa: ARG001
            raise RuntimeError("Request exception!")

        monkeypatch.setattr(app.state.runtime, "execute_opportunity", fail_execute)

        response = client.post("/opportunities/opp_test/execute")

        assert response.status_code == 502
        assert response.json()["detail"] == "Request exception!"


def test_research_threshold_route_updates_runtime_risk_config() -> None:
    os.environ["DATABASE_URL"] = "sqlite:///:memory:"
    os.environ["ENABLE_RESEARCH_MODE"] = "true"
    get_settings.cache_clear()
    from app.main import app

    with TestClient(app) as client:
        response = client.post("/settings/research-thresholds", json={"research_signal_min_net_edge": 0.003})
        settings = client.get("/settings")

        assert response.status_code == 200
        assert response.json()["research_signal_min_net_edge"] == 0.003
        assert settings.json()["risk"]["research_signal_min_net_edge"] == 0.003
