from __future__ import annotations

from datetime import UTC, datetime
import logging
from typing import Any

import httpx

from app.core.settings import Settings

logger = logging.getLogger(__name__)


class ClaudeClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.operator_enabled: bool = settings.enable_claude_agent
        self.runtime_allowed: bool = True
        self.runtime_state: str | None = None
        self.runtime_message: str | None = None
        self.last_status: str = "not_configured" if not settings.anthropic_api_key else ("disabled_by_operator" if not self.operator_enabled else "idle")
        self.last_error: dict[str, Any] | None = None
        self.last_checked_at: datetime | None = None
        self.last_model_used: str | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.settings.anthropic_api_key) and self.operator_enabled and self.runtime_allowed

    def set_operator_enabled(self, enabled: bool) -> None:
        self.operator_enabled = enabled
        self.last_checked_at = datetime.now(UTC)
        if enabled:
            if self.last_status == "disabled_by_operator":
                self.last_status = "idle"
                self.last_error = None
        else:
            self.last_status = "disabled_by_operator"
            self.last_error = {"message": "Claude was disabled from the dashboard/runtime control."}

    def set_runtime_access(self, *, allowed: bool, state: str | None = None, message: str | None = None) -> None:
        self.runtime_allowed = allowed
        self.runtime_state = state
        self.runtime_message = message
        if allowed and self.last_status in {"disabled_demo_mode", "disabled_runtime"}:
            self.last_status = "idle"
            self.last_error = None

    def connection_status(self) -> dict[str, Any]:
        message = "Claude API key is not configured."
        state = self.last_status
        error = self.last_error

        if not self.settings.anthropic_api_key:
            state = "not_configured"
            message = "Claude API key is not configured."
        elif not self.operator_enabled:
            state = "disabled_by_operator"
            message = "Claude is disabled by the runtime/dashboard control."
        elif not self.runtime_allowed:
            state = self.runtime_state or "disabled_runtime"
            message = self.runtime_message or "Claude is disabled for the current runtime state."
        elif self.last_status == "ok":
            message = "Claude API is reachable and returning completions."
        elif self.last_status == "idle":
            message = "Claude is configured but not yet exercised in this process."
        elif self.last_status == "billing_blocked":
            message = "Claude API is reachable, but Anthropic billing/credits are blocking inference."
        elif self.last_status == "auth_error":
            message = "Claude API rejected the key."
        elif self.last_status == "permission_denied":
            message = "Claude API denied access to the requested resource or model."
        elif self.last_status == "request_error":
            message = "Claude API received the request but rejected its contents."
        elif self.last_status == "transport_error":
            message = "Claude API could not be reached from this runtime."
        return {
            "configured": bool(self.settings.anthropic_api_key),
            "enabled": self.enabled,
            "operator_enabled": self.operator_enabled,
            "state": state,
            "message": message,
            "model": self.last_model_used or self.settings.anthropic_model,
            "last_checked_at": self.last_checked_at,
            "error": error,
        }

    def _record_success(self, model: str) -> None:
        self.last_status = "ok"
        self.last_error = None
        self.last_checked_at = datetime.now(UTC)
        self.last_model_used = model

    def _record_error(self, *, state: str, error: dict[str, Any]) -> None:
        self.last_status = state
        self.last_error = error
        self.last_checked_at = datetime.now(UTC)
        self.last_model_used = self.settings.anthropic_model

    def _disabled_response(self, text: str, *, state: str, error: dict[str, Any] | None = None) -> dict[str, Any]:
        self.last_status = state
        self.last_error = error
        self.last_checked_at = datetime.now(UTC)
        self.last_model_used = self.settings.anthropic_model
        return {
            "text": text,
            "usage": {"input_tokens": 0, "output_tokens": 0},
            "model": self.settings.anthropic_model,
            "error": error,
        }

    async def complete(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        if not self.settings.anthropic_api_key:
            return self._disabled_response(
                "Claude is not configured. Returning deterministic local summary only.",
                state="not_configured",
                error={"message": "ANTHROPIC_API_KEY is missing."},
            )
        if not self.operator_enabled:
            return self._disabled_response(
                "Claude is disabled by runtime control, so the system used a deterministic local fallback.",
                state="disabled_by_operator",
                error={"message": "Claude runtime toggle is off."},
            )
        if not self.runtime_allowed:
            return self._disabled_response(
                self.runtime_message or "Claude is disabled for the current runtime state, so the system used a deterministic local fallback.",
                state=self.runtime_state or "disabled_runtime",
                error={"message": self.runtime_message or "Claude runtime-disabled."},
            )

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
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                response = await client.post(self.settings.anthropic_api_url, headers=headers, json=payload)
                response.raise_for_status()
                body = response.json()
        except httpx.HTTPStatusError as exc:
            error_body = exc.response.text[:400]
            lowered = error_body.lower()
            if "credit balance is too low" in lowered:
                state = "billing_blocked"
            elif exc.response.status_code == 401:
                state = "auth_error"
            elif exc.response.status_code == 403:
                state = "permission_denied"
            else:
                state = "request_error"
            logger.warning(
                "claude request failed",
                extra={
                    "event": "claude_request_failed",
                    "status_code": exc.response.status_code,
                    "model": self.settings.anthropic_model,
                    "response_body": error_body,
                },
            )
            error = {"status_code": exc.response.status_code, "body": error_body}
            self._record_error(state=state, error=error)
            return {
                "text": (
                    "Claude request failed, so the system used a deterministic local fallback. "
                    "Check ANTHROPIC_MODEL, ANTHROPIC_API_KEY, and the Anthropic response body in logs."
                ),
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "model": self.settings.anthropic_model,
                "error": error,
            }
        except httpx.HTTPError as exc:
            logger.warning(
                "claude request transport error",
                extra={"event": "claude_transport_error", "error_message": str(exc), "model": self.settings.anthropic_model},
            )
            error = {"message": str(exc)}
            self._record_error(state="transport_error", error=error)
            return {
                "text": "Claude transport failed, so the system used a deterministic local fallback.",
                "usage": {"input_tokens": 0, "output_tokens": 0},
                "model": self.settings.anthropic_model,
                "error": error,
            }

        text_parts = [item.get("text", "") for item in body.get("content", []) if item.get("type") == "text"]
        self._record_success(body.get("model", self.settings.anthropic_model))
        return {
            "text": "\n".join(part for part in text_parts if part).strip(),
            "usage": body.get("usage", {}),
            "model": body.get("model", self.settings.anthropic_model),
        }
