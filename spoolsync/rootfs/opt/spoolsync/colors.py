"""Bambu Lab's names of its filament colours ("Azurblau", "Jade White").

The apps take them from a table that ships with Bambu Studio; SpoolSync loads the same file and
keeps it for a week.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path

import aiohttp

_LOG = logging.getLogger(__name__)
URL = ("https://raw.githubusercontent.com/bambulab/BambuStudio/master/resources/profiles/BBL/"
       "filament/filaments_color_codes.json")
MAX_AGE_S = 7 * 24 * 3600


class ColorNames:
    def __init__(self, cache: Path, language: str = ""):
        self.cache = cache
        self.language = language
        self._table: dict[tuple[str, str], dict] | None = None
        self._loaded_at = 0.0

    async def _load(self) -> None:
        if self._table is not None and time.time() - self._loaded_at < MAX_AGE_S:
            return
        data = None
        try:
            if time.time() - self.cache.stat().st_mtime < MAX_AGE_S:
                data = json.loads(self.cache.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if data is None:
            try:
                timeout = aiohttp.ClientTimeout(total=20)
                async with aiohttp.ClientSession(timeout=timeout) as s, s.get(URL) as r:
                    r.raise_for_status()
                    data = json.loads(await r.text())
                self.cache.parent.mkdir(parents=True, exist_ok=True)
                self.cache.write_text(json.dumps(data), encoding="utf-8")
            except (aiohttp.ClientError, TimeoutError, ValueError, OSError) as err:
                _LOG.warning("Farbtabelle von Bambu Lab nicht ladbar: %s", err)
                try:  # an old copy is better than none
                    data = json.loads(self.cache.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}
        self._table = table(data)
        self._loaded_at = time.time()

    async def name(self, filament_id: str, color: str) -> str:
        """The name of an official colour – '' for other filament or an unknown colour."""
        if not filament_id or not color:
            return ""
        await self._load()
        names = self._table.get((filament_id.upper(), color.upper()))
        if not names:
            return ""
        return names.get(self.language) or names.get("en") or ""


def table(data: dict) -> dict[tuple[str, str], dict]:
    """(filament id, RRGGBB) -> names by language; only single-colour filament."""
    result = {}
    for entry in (data or {}).get("data") or []:
        colors = entry.get("fila_color") or []
        if len(colors) != 1 or not entry.get("fila_id"):
            continue
        key = (str(entry["fila_id"]).upper(), str(colors[0]).lstrip("#")[:6].upper())
        result.setdefault(key, entry.get("fila_color_name") or {})
    return result
