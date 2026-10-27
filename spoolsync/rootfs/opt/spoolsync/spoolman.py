"""Spoolman REST API (https://github.com/Donkie/Spoolman, /api/v1)."""

from __future__ import annotations

import logging

import aiohttp

from .model import Spool, norm_color, to_grams

_LOG = logging.getLogger(__name__)

# Spoolman needs a density for every filament; used when a spool from the cloud brings a new one
DENSITY = {
    "PLA": 1.24, "PETG": 1.27, "PET": 1.27, "ABS": 1.04, "ASA": 1.07, "TPU": 1.21, "PA": 1.14,
    "PC": 1.20, "PVA": 1.23, "HIPS": 1.04, "PP": 0.90, "PPS": 1.35, "PET-CF": 1.30,
}


def density_for(material: str) -> float:
    m = (material or "").upper()
    if m in DENSITY:
        return DENSITY[m]
    for key, value in DENSITY.items():
        if m.startswith(key):
            return value
    return 1.24


class SpoolmanError(Exception):
    pass


class Spoolman:
    def __init__(self, base_url: str, session: aiohttp.ClientSession | None = None):
        self.base = base_url.rstrip("/").removesuffix("/api/v1")
        self._session = session
        self._filaments: list[dict] | None = None
        self._vendors: list[dict] | None = None

    async def _req(self, method: str, path: str, **kwargs):
        if self._session is None:
            self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
        url = f"{self.base}/api/v1{path}"
        try:
            async with self._session.request(method, url, **kwargs) as resp:
                if resp.status >= 400:
                    body = (await resp.text())[:300]
                    raise SpoolmanError(f"{method} {path}: HTTP {resp.status} {body}")
                if resp.status == 204:
                    return None
                return await resp.json(content_type=None)
        except aiohttp.ClientError as err:
            raise SpoolmanError(f"Spoolman nicht erreichbar ({self.base}): {err}") from err

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()

    # --- reading -------------------------------------------------------------------------------

    async def list_spools(self) -> list[Spool]:
        self._filaments = None
        self._vendors = None
        raw = await self._req("GET", "/spool", params={"allow_archived": "true"})
        return [to_spool(item) for item in raw or []]

    async def _all_filaments(self) -> list[dict]:
        if self._filaments is None:
            self._filaments = list(await self._req("GET", "/filament") or [])
        return self._filaments

    async def _all_vendors(self) -> list[dict]:
        if self._vendors is None:
            self._vendors = list(await self._req("GET", "/vendor") or [])
        return self._vendors

    # --- writing -------------------------------------------------------------------------------

    async def vendor_id(self, name: str) -> int | None:
        if not name:
            return None
        for v in await self._all_vendors():
            if (v.get("name") or "").casefold() == name.casefold():
                return v["id"]
        created = await self._req("POST", "/vendor", json={"name": name})
        self._vendors.append(created)
        _LOG.info("Spoolman: Hersteller %s angelegt", name)
        return created["id"]

    async def filament_id(self, s: Spool, like: dict | None = None) -> int:
        """The filament with vendor, name, material and colour of ``s`` – created if missing.

        ``like`` is the filament the spool used so far: diameter, density and spool weight are
        taken over from it.
        """
        vid = await self.vendor_id(s.vendor)
        name = s.name or s.material
        for f in await self._all_filaments():
            vendor = (f.get("vendor") or {}).get("id")
            if (vendor == vid and (f.get("name") or "").casefold() == name.casefold()
                    and (f.get("material") or "").casefold() == (s.material or "").casefold()
                    and norm_color(f.get("color_hex")) == s.color):
                return f["id"]
        like = like or {}
        body = {
            "name": name,
            "material": s.material or None,
            "density": like.get("density") or density_for(s.material),
            "diameter": like.get("diameter") or 1.75,
        }
        if vid is not None:
            body["vendor_id"] = vid
        if s.color:
            body["color_hex"] = s.color
        weight = s.total_g or like.get("weight")
        if weight:
            body["weight"] = weight
        for key in ("spool_weight", "settings_extruder_temp", "settings_bed_temp"):
            if like.get(key) is not None:
                body[key] = like[key]
        created = await self._req("POST", "/filament", json=body)
        self._filaments.append(created)
        _LOG.info("Spoolman: Filament %s angelegt", name)
        return created["id"]

    async def create(self, s: Spool) -> int:
        body = {"filament_id": await self.filament_id(s)}
        if s.total_g is not None:
            body["initial_weight"] = s.total_g
        if s.remaining_g is not None:
            body["remaining_weight"] = s.remaining_g
        if s.note:
            body["comment"] = s.note
        created = await self._req("POST", "/spool", json=body)
        return int(created["id"])

    async def update(self, current: Spool, changes: dict) -> None:
        # Vendor, name, material and colour belong to the filament, which other spools may share:
        # the spool is moved to the filament that fits instead of changing it for all of them.
        if any(f in changes for f in ("vendor", "material", "name", "color")):
            target = Spool(current.id, **{
                f: changes.get(f, getattr(current, f))
                for f in ("vendor", "material", "name", "color", "total_g")})
            fid = await self.filament_id(target, like=current.extra.get("filament"))
            await self._req("PATCH", f"/spool/{current.id}", json={"filament_id": fid})
        # the initial weight first: Spoolman derives the used weight from it and the remainder
        if "total_g" in changes:
            await self._req("PATCH", f"/spool/{current.id}",
                            json={"initial_weight": changes["total_g"]})
        body = {}
        if "remaining_g" in changes:
            body["remaining_weight"] = max(changes["remaining_g"], 0)
        if "note" in changes:
            body["comment"] = changes["note"] or ""
        if body:
            await self._req("PATCH", f"/spool/{current.id}", json=body)

    async def archive(self, spool_id: int) -> None:
        await self._req("PATCH", f"/spool/{spool_id}", json={"archived": True})


def to_spool(item: dict) -> Spool:
    filament = item.get("filament") or {}
    vendor = filament.get("vendor") or {}
    extra = item.get("extra") or {}
    rfid = ""
    for key in ("tag", "rfid", "tray_uuid"):
        value = extra.get(key)
        if value:
            rfid = str(value).strip('"')
            break
    total = item.get("initial_weight")
    if total is None:
        total = filament.get("weight")
    return Spool(
        id=int(item["id"]),
        vendor=vendor.get("name") or "",
        material=filament.get("material") or "",
        name=filament.get("name") or "",
        color=norm_color(filament.get("color_hex")
                         or (filament.get("multi_color_hexes") or "").split(",")[0]),
        total_g=to_grams(total),
        remaining_g=to_grams(item.get("remaining_weight")),
        note=item.get("comment") or "",
        archived=bool(item.get("archived")),
        rfid=rfid,
        extra={"filament": filament, "location": item.get("location") or ""},
    )
