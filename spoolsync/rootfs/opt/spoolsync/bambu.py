"""Filament library of the Bambu Lab cloud – what Bambu Studio and Bambu Handy show as spools.

The API is not documented by Bambu Lab; endpoints and fields follow what the apps use. The cloud is
behind Cloudflare, which turns away plain Python HTTP clients: requests go through curl_cffi with a
browser fingerprint when it is installed.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path

from .model import Spool, norm_color, to_grams

_LOG = logging.getLogger(__name__)

API = {"global": "https://api.bambulab.com", "china": "https://api.bambulab.cn"}
WEB = {"global": "https://bambulab.com", "china": "https://bambulab.cn"}
FILAMENT = "/v1/design-user-service/my/filament/v2"
PAGE = 100
# the slicer's headers – the cloud treats the requests like those of a slicer
HEADERS = {
    "User-Agent": "bambu_network_agent/01.09.05.01",
    "X-BBL-Client-Name": "OrcaSlicer",
    "X-BBL-Client-Type": "slicer",
    "X-BBL-Client-Version": "01.09.05.51",
    "X-BBL-Language": "en-US",
    "X-BBL-OS-Type": "linux",
    "X-BBL-OS-Version": "6.2.0",
    "X-BBL-Agent-Version": "01.09.05.01",
    "X-BBL-Executable-info": "{}",
    "X-BBL-Agent-OS-Type": "linux",
    "Accept": "application/json",
}

# Slicer profiles for filament of other brands, by material ("Generic PLA" ...)
GENERIC = {
    "PLA": "GFL99", "PLA-CF": "GFL98", "PLA SILK": "GFL96", "PETG": "GFG99", "PET": "GFG99",
    "ABS": "GFB99", "ASA": "GFB98", "TPU": "GFU99", "PA": "GFN99", "PC": "GFC99", "PVA": "GFS99",
    "HIPS": "GFS98",
}

# our field -> field of the cloud
_FIELD = {
    "vendor": "filamentVendor",
    "material": "filamentType",
    "name": "filamentName",
    "total_g": "totalNetWeight",
    "remaining_g": "netWeight",
    "note": "note",
}


class BambuError(Exception):
    pass


class AuthRequired(BambuError):
    """No valid sign-in (never signed in, or the token of about 90 days ran out)."""


class _Http:
    """Small async HTTP wrapper: curl_cffi (browser fingerprint) or aiohttp as fallback."""

    def __init__(self):
        self._session = None
        self._curl = None

    async def request(self, method: str, url: str, *, json_body=None, params=None,
                      headers=None) -> tuple[int, str, dict]:
        if self._curl is None:
            try:
                from curl_cffi.requests import AsyncSession
                self._session = AsyncSession(impersonate="chrome", timeout=20)
                self._curl = True
            except ImportError:
                import aiohttp
                self._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=20))
                self._curl = False
        try:
            if self._curl:
                r = await self._session.request(method, url, json=json_body, params=params,
                                                headers=headers)
                return r.status_code, r.text, dict(r.cookies)
            async with self._session.request(method, url, json=json_body, params=params,
                                             headers=headers) as r:
                text = await r.text()
                return r.status, text, {k: v.value for k, v in r.cookies.items()}
        except BambuError:
            raise
        except Exception as err:  # network errors of both libraries
            raise BambuError(f"Bambu-Cloud nicht erreichbar: {err}") from err

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()


class Bambu:
    def __init__(self, token_file: Path, http: _Http | None = None):
        self.token_file = token_file
        self.http = http or _Http()
        self.token = ""
        self.email = ""
        self.region = "global"
        self._pending: dict = {}  # sign-in waiting for a code
        self._catalog: list[dict] | None = None
        self._load()

    # --- sign-in -------------------------------------------------------------------------------

    def _load(self) -> None:
        try:
            data = json.loads(self.token_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        self.token = data.get("token", "")
        self.email = data.get("email", "")
        self.region = data.get("region", "global")

    def _save(self) -> None:
        self.token_file.parent.mkdir(parents=True, exist_ok=True)
        self.token_file.write_text(json.dumps({
            "token": self.token, "email": self.email, "region": self.region,
            "saved_at": int(time.time())}), encoding="utf-8")

    @property
    def signed_in(self) -> bool:
        return bool(self.token)

    @property
    def expires_at(self) -> float | None:
        """End of the sign-in (from the token), None when unknown."""
        try:
            payload = self.token.split(".")[1]
            data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
            return float(data["exp"])
        except (IndexError, ValueError, KeyError, TypeError):
            return None

    def sign_out(self) -> None:
        self.token = ""
        self._pending = {}
        try:
            self.token_file.unlink()
        except OSError:
            pass

    async def login(self, email: str, password: str, region: str = "global") -> str:
        """Returns 'ok', 'code' (code sent by e-mail) or 'tfa' (code of the authenticator app)."""
        self.region = region if region in API else "global"
        status, text, _ = await self.http.request(
            "POST", f"{API[self.region]}/v1/user-service/user/login",
            json_body={"account": email, "password": password, "apiError": ""},
            headers=HEADERS)
        data = _json(text)
        if status >= 400:
            raise BambuError(_message(data, text, "Anmeldung fehlgeschlagen"))
        if data.get("accessToken"):
            self._signed_in(email, data["accessToken"])
            return "ok"
        kind = data.get("loginType")
        if kind == "verifyCode":
            # the cloud only asks for a code – sending it has to be requested
            self._pending = {"email": email, "kind": "code"}
            await self.resend_code()
            return "code"
        if kind == "tfa":
            self._pending = {"email": email, "kind": "tfa", "tfa_key": data.get("tfaKey", "")}
            return "tfa"
        raise BambuError(_message(data, text, "Unerwartete Antwort bei der Anmeldung"))

    async def submit_code(self, code: str) -> str:
        if not self._pending:
            raise BambuError("Keine Anmeldung offen – bitte zuerst E-Mail und Passwort senden.")
        code = code.strip()
        email = self._pending["email"]
        if self._pending["kind"] == "tfa":
            web = WEB[self.region]
            _, _, cookies = await self.http.request("GET", f"{web}/api/csrf")
            csrf = cookies.get("bbl_csrf_token", "")
            status, text, cookies = await self.http.request(
                "POST", f"{web}/api/sign-in/tfa",
                json_body={"tfaKey": self._pending["tfa_key"], "tfaCode": code},
                headers={"x-bbl-csrf-token": csrf, "Cookie": f"bbl_csrf_token={csrf}"})
            token = cookies.get("token") or _json(text).get("accessToken")
        else:
            status, text, _ = await self.http.request(
                "POST", f"{API[self.region]}/v1/user-service/user/login",
                json_body={"account": email, "code": code}, headers=HEADERS)
            data = _json(text)
            token = data.get("accessToken")
            if status == 400 and data.get("code") == 1:
                await self.resend_code()
                raise BambuError("Der Code ist abgelaufen – ein neuer Code wurde verschickt.")
            if status == 400 and data.get("code") == 2:
                raise BambuError("Der Code stimmt nicht.")
        if status >= 400 or not token:
            raise BambuError(_message(_json(text), text, "Code nicht angenommen"))
        self._signed_in(email, token)
        return "ok"

    async def resend_code(self) -> None:
        if not self._pending or self._pending["kind"] != "code":
            raise BambuError("Kein E-Mail-Code angefordert.")
        status, text, _ = await self.http.request(
            "POST", f"{API[self.region]}/v1/user-service/user/sendemail/code",
            json_body={"email": self._pending["email"], "type": "codeLogin"}, headers=HEADERS)
        if status >= 400:
            _LOG.warning("Code anfordern: HTTP %s %s", status, text[:300])
            raise BambuError(_message(_json(text), text, f"Code nicht verschickt (HTTP {status})"))
        _LOG.info("Anmeldecode per E-Mail angefordert")

    def _signed_in(self, email: str, token: str) -> None:
        self.email = email
        self.token = token
        self._pending = {}
        self._save()
        _LOG.info("Bei der Bambu-Cloud angemeldet")

    @property
    def pending(self) -> str:
        return self._pending.get("kind", "")

    # --- filament library ----------------------------------------------------------------------

    async def _api(self, method: str, path: str, *, json_body=None, params=None):
        if not self.token:
            raise AuthRequired("Nicht bei der Bambu-Cloud angemeldet.")
        status, text, _ = await self.http.request(
            method, f"{API[self.region]}{path}", json_body=json_body, params=params,
            headers={**HEADERS, "Authorization": f"Bearer {self.token}"})
        if status == 401:
            raise AuthRequired("Die Anmeldung bei der Bambu-Cloud ist abgelaufen.")
        if status == 403 or (status >= 400 and "cloudflare" in text[:2000].lower()):
            raise BambuError(f"Bambu-Cloud blockiert die Anfrage (HTTP {status}).")
        if status >= 400:
            raise BambuError(f"{method} {path}: HTTP {status} {text[:300]}")
        return _json(text)

    async def list_spools(self) -> list[Spool]:
        result: list[Spool] = []
        offset = 0
        for _ in range(50):
            data = await self._api("GET", FILAMENT, params={"offset": offset, "limit": PAGE})
            hits = data.get("hits") or []
            result += [to_spool(h) for h in hits]
            offset += len(hits)
            if not hits or offset >= int(data.get("total") or 0):
                break
        return result

    async def _filament_id(self, s: Spool) -> str:
        """Slicer profile of the spool: the official filament ("GFA00"), else the generic profile
        of the material ("Generic PLA"), else ''."""
        if self._catalog is None:
            try:
                self._catalog = _catalog_items(
                    await self._api("GET", "/v1/design-user-service/filament/config"))
            except BambuError as err:
                _LOG.warning("Filamentkatalog nicht lesbar: %s", err)
                self._catalog = []
        # the official name, also when a colour follows it ("PLA Basic Jade White")
        best, found = "", ""
        name = s.name.casefold()
        for item in self._catalog:
            cat = (item.get("name") or "").casefold()
            if ((item.get("vendor") or "").casefold() == s.vendor.casefold() and cat
                    and (name == cat or name.startswith(cat + " ")) and len(cat) > len(best)):
                best, found = cat, item.get("filament_id") or ""
        if best:
            return found
        material = (s.material or "").upper()
        if "SILK" in (s.name or "").upper() and material == "PLA":
            return GENERIC["PLA SILK"]
        return GENERIC.get(material) or GENERIC.get(material.rstrip("+"), "")

    async def _write(self, method: str, body: dict) -> None:
        """Create / change a spool; a profile the cloud does not take is left out."""
        try:
            await self._api(method, FILAMENT, json_body=body)
        except AuthRequired:
            raise
        except BambuError as err:
            if not body.get("filamentId") or "HTTP 400" not in str(err):
                raise
            _LOG.info("Profil %s nicht angenommen, Spule ohne Profil: %s", body["filamentId"], err)
            await self._api(method, FILAMENT, json_body={**body, "filamentId": ""})

    async def create(self, s: Spool) -> int:
        before = {b.id for b in await self.list_spools()}
        body = {
            "createType": "manual",
            "filamentVendor": s.vendor or "Generic",
            "filamentType": s.material or "PLA",
            "filamentName": s.name or s.material or "PLA",
            "color": f"#{s.color or 'FFFFFF'}",
            "colorType": 2,
            "isSupport": False,
            "netWeight": s.remaining_g if s.remaining_g is not None else (s.total_g or 1000),
            "totalNetWeight": s.total_g or 1000,
            "filamentId": await self._filament_id(s),
        }
        await self._write("POST", body)
        # the answer is empty: the new spool is the newest one with this vendor and name
        new = [b for b in await self.list_spools() if b.id not in before
               and b.vendor.casefold() == body["filamentVendor"].casefold()
               and b.name.casefold() == body["filamentName"].casefold()]
        if not new:
            raise BambuError("Spule angelegt, aber in der Bambu-Cloud nicht wiedergefunden.")
        new_id = max(b.id for b in new)
        if s.note:  # the create call does not take a note
            await self.update(new[0] if len(new) == 1 else Spool(new_id, name=body["filamentName"]),
                              {"note": s.note})
        return new_id

    async def update(self, current: Spool, changes: dict) -> None:
        # Only the changed values: a full copy would overwrite what the AMS reports meanwhile.
        body: dict = {"id": current.id,
                      "filamentName": changes.get("name", current.name) or current.material}
        for f, value in changes.items():
            if f == "color":
                body["color"] = f"#{value}"
                body["colors"] = [f"#{value}"]  # the apps show "colors" over "color"
            elif f in _FIELD:
                body[_FIELD[f]] = value
        # a spool that has a profile keeps it when only the name changes (e.g. a colour added)
        if (any(f in changes for f in ("vendor", "material"))
                or ("name" in changes and not current.extra.get("filamentId"))):
            target = Spool(current.id, vendor=changes.get("vendor", current.vendor),
                           name=changes.get("name", current.name),
                           material=changes.get("material", current.material))
            body["filamentId"] = await self._filament_id(target)
        await self._write("PUT", body)

    async def delete(self, spool_id: int) -> None:
        await self._api("DELETE", f"{FILAMENT}/batch", json_body={"ids": [spool_id]})

    async def tasks(self, limit: int = 30) -> list[dict]:
        """The latest print jobs of all printers of the account, newest first."""
        data = await self._api("GET", "/v1/user-service/my/tasks", params={"limit": limit})
        return [t for t in data.get("hits") or [] if isinstance(t, dict)]

    async def close(self) -> None:
        await self.http.close()


def to_spool(item: dict) -> Spool:
    colors = item.get("colors") or []
    status = item.get("status")
    return Spool(
        id=int(item["id"]),
        vendor=item.get("filamentVendor") or "",
        material=item.get("filamentType") or "",
        name=item.get("filamentName") or "",
        color=norm_color(colors[0] if colors else item.get("color")),
        total_g=to_grams(item.get("totalNetWeight")),
        remaining_g=to_grams(item.get("netWeight")),
        note=item.get("note") or "",
        archived=status not in (None, 0, "0"),
        rfid=item.get("RFID") or "",
        location=slot_text(item),
        extra={k: item.get(k) for k in ("filamentId", "createType", "deviceName", "inPrinter",
                                        "devId", "amsId", "slotId", "trayIdName")},
    )


def slot_text(item: dict) -> str:
    """Where the spool sits: "Drucker – AMS 1 Slot 2"; '' when it is not in a printer."""
    if not item.get("inPrinter"):
        return ""
    printer = item.get("deviceName") or "Drucker"
    try:
        ams, slot = int(item.get("amsId")), int(item.get("slotId"))
    except (TypeError, ValueError):
        return printer
    if 128 <= ams < 136:
        return f"{printer} – AMS HT {ams - 127}"
    if 0 <= ams < 8:
        return f"{printer} – AMS {ams + 1} Slot {slot + 1}"
    return f"{printer} – externe Spule"


def _catalog_items(data) -> list[dict]:
    """The catalogue entries, wherever the answer keeps the list."""
    if isinstance(data, list):
        if any(isinstance(i, dict) and "filament_id" in i for i in data):
            return [i for i in data if isinstance(i, dict)]
        found = []
        for i in data:
            found += _catalog_items(i)
        return found
    if isinstance(data, dict):
        found = []
        for value in data.values():
            if isinstance(value, (list, dict)):
                found += _catalog_items(value)
        return found
    return []


def _json(text: str) -> dict:
    try:
        data = json.loads(text) if text else {}
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {"data": data}


def _message(data: dict, text: str, default: str) -> str:
    for key in ("message", "error", "msg"):
        if data.get(key):
            return f"{default}: {data[key]}"
    return f"{default} ({text[:200]})" if text else default
