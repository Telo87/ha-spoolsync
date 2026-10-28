"""Home Assistant through the Supervisor: notifications and the language of the installation."""

from __future__ import annotations

import logging
import os

import aiohttp

_LOG = logging.getLogger(__name__)
API = "http://supervisor/core/api"


class HomeAssistant:
    def __init__(self, enabled: bool = True):
        self.token = os.environ.get("SUPERVISOR_TOKEN", "")
        self.enabled = enabled and bool(self.token)
        self.shown: dict[str, str] = {}  # notification key -> message shown
        self._session: aiohttp.ClientSession | None = None

    async def _post(self, path: str, body: dict) -> dict | list | None:
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        async with self._session.post(f"{API}{path}", json=body,
                                      headers={"Authorization": f"Bearer {self.token}"}) as r:
            r.raise_for_status()
            return await r.json(content_type=None)

    async def language(self) -> str:
        if not self.token:
            return ""
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10))
        try:
            async with self._session.get(f"{API}/config",
                                         headers={"Authorization": f"Bearer {self.token}"}) as r:
                r.raise_for_status()
                return ((await r.json()).get("language") or "").split("-")[0]
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            _LOG.debug("Sprache von Home Assistant nicht lesbar: %s", err)
            return ""

    async def notify(self, key: str, title: str, message: str) -> None:
        """Shows a notification once – again only when the message changes."""
        if self.shown.get(key) == message:
            return
        self.shown[key] = message
        if not self.enabled:
            _LOG.info("Hinweis: %s – %s", title, message)
            return
        try:
            await self._post("/services/persistent_notification/create",
                             {"notification_id": f"spoolsync_{key}", "title": title,
                              "message": message})
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOG.warning("Benachrichtigung nicht möglich: %s", err)

    async def dismiss(self, key: str) -> None:
        if self.shown.pop(key, None) is None or not self.enabled:
            return
        try:
            await self._post("/services/persistent_notification/dismiss",
                             {"notification_id": f"spoolsync_{key}"})
        except (aiohttp.ClientError, TimeoutError) as err:
            _LOG.debug("Benachrichtigung nicht entfernt: %s", err)

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
