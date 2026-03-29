from __future__ import annotations

from typing import Any

import httpx

from app.core.settings import Settings


class ClaudeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def enabled(self) -> bool:
        return bool(self.settings.anthropic_api_key)

    async def complete(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.enabled:
            return {
                "text": "Claude is not configured. Returning deterministic local summary only.",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "model": self.settings.anthropic_model,
            }

        headers = {
            "x-api-key": self.settings.anthropic_api_key,
            "anthropic-version": self.settings.anthropic_version,
            "content-type": "application/json",
        }
        payload = {
            "model": self.settings.anthropic_model,
            "max_tokens": self.settings.anthropic_max_tokens,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        async with httpx.AsyncClient(timeout=20.0) as client:
            response = await client.post(self.settings.anthropic_api_url, headers=headers, json=payload)
            response.raise_for_status()
            body = response.json()

        text_parts = [item.get("text", "") for item in body.get("content", []) if item.get("type") == "text"]
        return {
            "text": "\n".join(part for part in text_parts if part).strip(),
            "usage": body.get("usage", {}),
            "model": body.get("model", self.settings.anthropic_model),
        }

