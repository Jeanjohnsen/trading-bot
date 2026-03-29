from __future__ import annotations

import httpx

from app.core.settings import Settings
from app.domain.models import NotificationMessage
from app.storage.repositories import Repository


class NotificationDispatcher:
    def __init__(self, settings: Settings, repository: Repository) -> None:
        self.settings = settings
        self.repository = repository

    async def dispatch(self, notification: NotificationMessage) -> None:
        self.repository.save_notification(notification)
        if self.settings.webhook_url:
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(self.settings.webhook_url, json=notification.model_dump(mode="json"))
