import asyncio

import httpx

from app.agents.claude_client import ClaudeClient
from app.core.settings import Settings


class ErrorResponse:
    def __init__(self, status_code: int, text: str) -> None:
        self.status_code = status_code
        self.text = text

    def raise_for_status(self) -> None:
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        response = httpx.Response(self.status_code, request=request, text=self.text)
        raise httpx.HTTPStatusError("bad request", request=request, response=response)

    def json(self) -> dict:
        return {}


def test_claude_client_falls_back_on_http_400(monkeypatch) -> None:
    async def fake_post(self, url, headers=None, json=None):  # noqa: ARG001
        return ErrorResponse(400, '{"error":{"message":"Your credit balance is too low to access the Anthropic API."}}')

    monkeypatch.setattr(httpx.AsyncClient, "post", fake_post)
    settings = Settings(ANTHROPIC_API_KEY="test-key", ANTHROPIC_MODEL="bad-model")
    client = ClaudeClient(settings)
    response = asyncio.run(client.complete("system", "user"))

    assert "deterministic local fallback" in response["text"].lower()
    assert response["error"]["status_code"] == 400
    assert client.connection_status()["state"] == "billing_blocked"


def test_claude_client_is_disabled_by_runtime_demo_mode() -> None:
    settings = Settings(ANTHROPIC_API_KEY="test-key", ENABLE_CLAUDE_AGENT=True)
    client = ClaudeClient(settings)
    client.set_runtime_access(
        allowed=False,
        state="disabled_demo_mode",
        message="Claude is disabled while demo/bootstrap market data is active.",
    )

    response = asyncio.run(client.complete("system", "user"))

    assert response["error"]["message"] == "Claude is disabled while demo/bootstrap market data is active."
    assert client.connection_status()["state"] == "disabled_demo_mode"


def test_claude_client_is_disabled_by_explicit_flag() -> None:
    settings = Settings(ANTHROPIC_API_KEY="test-key", ENABLE_CLAUDE_AGENT=False)
    client = ClaudeClient(settings)

    response = asyncio.run(client.complete("system", "user"))

    assert response["error"]["message"] == "Claude runtime toggle is off."
    assert client.connection_status()["state"] == "disabled_by_operator"
