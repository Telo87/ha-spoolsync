"""Web interface behind Home Assistant ingress."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from aiohttp import web

from .bambu import BambuError
from .hub import Hub

_LOG = logging.getLogger(__name__)
STATIC = Path(__file__).parent / "static"
# Home Assistant's ingress proxy; nothing else is let in (no port is published)
INGRESS = {"172.30.32.2", "127.0.0.1", "::1"}


def create_app(hub: Hub) -> web.Application:
    allow_all = os.environ.get("SPOOLSYNC_ALLOW_ALL") == "1" or hub.opts.demo

    @web.middleware
    async def only_ingress(request: web.Request, handler):
        if not allow_all and request.remote not in INGRESS:
            raise web.HTTPForbidden(text="Nur über Home Assistant erreichbar.")
        return await handler(request)

    async def index(_request):
        return web.FileResponse(STATIC / "index.html",
                                headers={"Cache-Control": "no-cache"})

    async def state(_request):
        return web.json_response(hub.state())

    async def check(_request):
        async with hub.lock:
            await hub.refresh()
        return web.json_response(hub.state())

    async def run(_request):
        if hub.lock.locked():
            return web.json_response({"error": "Ein Abgleich läuft bereits."}, status=409)
        result = await hub.run()
        return web.json_response({"result": result, **hub.state()})

    async def login(request):
        body = await request.json()
        email = (body.get("email") or "").strip()
        password = body.get("password") or ""
        if not email or not password:
            return _error("Bitte E-Mail und Passwort angeben.")
        try:
            status = await hub.bambu.login(email, password, body.get("region") or "global")
        except BambuError as err:
            return _error(str(err))
        return await _after_login(status)

    async def code(request):
        body = await request.json()
        try:
            status = await hub.bambu.submit_code(body.get("code") or "")
        except BambuError as err:
            return _error(str(err))
        return await _after_login(status)

    async def resend(_request):
        try:
            await hub.bambu.resend_code()
        except BambuError as err:
            return _error(str(err))
        return web.json_response({"status": "code"})

    async def logout(_request):
        hub.bambu.sign_out()
        async with hub.lock:
            await hub.refresh()
        return web.json_response(hub.state())

    async def link(request):
        return await _pair(request, hub.link)

    async def unlink(request):
        return await _pair(request, hub.unlink)

    async def _pair(request, change):
        body = await request.json()
        try:
            sm_id, bb_id = int(body.get("sm")), int(body.get("bb"))
        except (TypeError, ValueError):
            return _error("Spulen fehlen.")
        async with hub.lock:
            try:
                await change(sm_id, bb_id)
            except ValueError as err:
                return _error(str(err))
            await hub.refresh()
        return web.json_response(hub.state())

    async def _after_login(status: str):
        if status == "ok":
            async with hub.lock:
                await hub.refresh()
        return web.json_response({"status": status, **hub.state()})

    app = web.Application(middlewares=[only_ingress])
    app.router.add_get("/", index)
    app.router.add_get("/api/state", state)
    app.router.add_post("/api/check", check)
    app.router.add_post("/api/sync", run)
    app.router.add_post("/api/login", login)
    app.router.add_post("/api/code", code)
    app.router.add_post("/api/resend", resend)
    app.router.add_post("/api/logout", logout)
    app.router.add_post("/api/link", link)
    app.router.add_post("/api/unlink", unlink)
    app.router.add_static("/static/", STATIC)
    return app


def _error(text: str, status: int = 400):
    return web.json_response({"error": text}, status=status)
