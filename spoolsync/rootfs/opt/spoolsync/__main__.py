"""Entry point: ``python3 -m spoolsync``."""

import asyncio
import logging

from aiohttp import web

from .bambu import Bambu
from .colors import ColorNames
from .config import DATA_DIR, load_options
from .demo import demo_sides
from .ha import HomeAssistant
from .hub import Hub
from .server import create_app
from .spoolman import Spoolman


def main() -> None:
    opts = load_options()
    logging.basicConfig(
        level=getattr(logging, opts.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )
    ha = HomeAssistant(opts.notifications and not opts.demo)
    if opts.demo:
        spoolman, bambu = demo_sides()
        colors = None
    else:
        spoolman, bambu = Spoolman(opts.spoolman_url), Bambu(DATA_DIR / "bambu.json")
        colors = ColorNames(DATA_DIR / "colors.json")
    hub = Hub(opts, spoolman, bambu, DATA_DIR, ha=ha, colors=colors)
    app = create_app(hub)

    async def start(_app):
        if colors is not None:
            colors.language = await ha.language() or "en"
        _app["loop"] = asyncio.create_task(hub.loop())

    async def stop(_app):
        _app["loop"].cancel()
        await spoolman.close()
        await bambu.close()
        await ha.close()

    app.on_startup.append(start)
    app.on_cleanup.append(stop)
    logging.getLogger("spoolsync").info("SpoolSync läuft auf Port %d", opts.port)
    web.run_app(app, host="0.0.0.0", port=opts.port, access_log=None, print=None)


if __name__ == "__main__":
    main()
