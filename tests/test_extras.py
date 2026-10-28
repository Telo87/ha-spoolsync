"""Printer slot as location, links kept in Spoolman, linking by hand, colour names, notices."""

import base64
import json
import time

from spoolsync.bambu import Bambu, slot_text
from spoolsync.colors import table
from spoolsync.config import Options
from spoolsync.demo import FakeBambu, FakeSpoolman
from spoolsync.hub import Hub
from spoolsync.model import Spool


def spool(id_, **kw):
    base = {"vendor": "JAYO", "material": "PLA", "name": "PLA Turquoise", "color": "38BAC0",
            "total_g": 1100, "remaining_g": 900}
    base.update(kw)
    return Spool(id_, **base)


class FakeHA:
    def __init__(self):
        self.shown = {}

    async def notify(self, key, title, message):
        self.shown[key] = message

    async def dismiss(self, key):
        self.shown.pop(key, None)


class FakeColors:
    async def name(self, filament_id, color):
        return {("GFB00", "489FDF"): "Azurblau"}.get((filament_id, color), "")


def make(tmp_path, sm, bb, **kw):
    smc, bbc = FakeSpoolman(sm), FakeBambu(bb)
    hub = Hub(Options(book_bambu_prints=False), smc, bbc, tmp_path, **kw)
    return hub, smc, bbc


# --- printer slot as location ---------------------------------------------------------------

def test_slot_texts():
    base = {"inPrinter": True, "deviceName": "H2C"}
    assert slot_text({**base, "amsId": 0, "slotId": "1"}) == "H2C – AMS 1 Slot 2"
    assert slot_text({**base, "amsId": 128, "slotId": "0"}) == "H2C – AMS HT 1"
    assert slot_text({**base, "amsId": 255, "slotId": "0"}) == "H2C – externe Spule"
    assert slot_text({"inPrinter": False, "amsId": 0, "slotId": 0}) == ""


async def test_slot_becomes_the_location_and_is_cleared_again(tmp_path):
    hub, smc, bbc = make(tmp_path, [spool(1)], [spool(100, location="H2C – AMS 1 Slot 2")])
    await hub.run()
    assert smc.spools[1].location == "H2C – AMS 1 Slot 2"
    bbc.spools[100].location = ""  # taken out of the printer
    await hub.run()
    assert smc.spools[1].location == ""


async def test_location_set_by_hand_stays(tmp_path):
    hub, smc, _bbc = make(tmp_path, [spool(1, location="Regal 3")], [spool(100)])
    await hub.run()
    assert smc.spools[1].location == "Regal 3"


# --- links kept in Spoolman -------------------------------------------------------------------

async def test_links_come_back_from_spoolman(tmp_path):
    hub, smc, bbc = make(tmp_path, [spool(1, remaining_g=500)], [spool(100, remaining_g=480)])
    await hub.run()
    assert smc.spools[1].extra["bambu_id"] == "100"
    (tmp_path / "links.json").unlink()  # e.g. reinstalled
    smc.spools[1].color = "000000"  # would no longer be matched by its values
    again = Hub(Options(book_bambu_prints=False), smc, bbc, tmp_path)
    await again.run()
    assert [(link.sm, link.bb) for link in again.links] == [(1, 100)]
    assert len(bbc.spools) == 1 and bbc.spools[100].color == "000000"


# --- linking by hand --------------------------------------------------------------------------

async def test_separated_spools_are_not_matched_again(tmp_path):
    hub, _smc, _bbc = make(tmp_path, [spool(1)], [spool(100)])
    await hub.run()
    await hub.unlink(1, 100)
    await hub.refresh()
    kinds = [a.kind for a in hub.plan.actions]
    assert "link" not in kinds
    assert kinds.count("create_bambu") == 1 and kinds.count("create_spoolman") == 1


async def test_link_by_hand(tmp_path):
    hub, _smc, _bbc = make(tmp_path, [spool(1)], [spool(100, color="000000", material="PETG")])
    await hub.refresh()
    await hub.link(1, 100)
    await hub.refresh()
    assert [(link.sm, link.bb) for link in hub.links] == [(1, 100)]
    assert {a.kind for a in hub.plan.writes} <= {"update_bambu", "update_spoolman"}


# --- colour names ----------------------------------------------------------------------------

def test_colour_table():
    data = {"data": [
        {"fila_id": "GFB00", "fila_color": ["#489FDFFF"],
         "fila_color_name": {"de": "Azurblau", "en": "Azure"}},
        {"fila_id": "GFA00", "fila_color": ["#FF0000FF", "#0000FFFF"],
         "fila_color_name": {"en": "Gradient"}},
    ]}
    assert table(data) == {("GFB00", "489FDF"): {"de": "Azurblau", "en": "Azure"}}


async def test_new_spoolman_spool_gets_the_bambu_colour_name(tmp_path):
    b = Spool(100, "Bambu Lab", "ABS", "ABS", "489FDF", 1000, 1000,
              extra={"filamentId": "GFB00"})
    hub, smc, _bbc = make(tmp_path, [], [b], colors=FakeColors())
    await hub.run()
    created = next(iter(smc.spools.values()))
    assert created.name == "ABS Azurblau"


async def test_catalogue_name_with_colour_keeps_the_profile(tmp_path):
    bambu = Bambu(tmp_path / "b.json")
    bambu._catalog = [{"vendor": "Bambu Lab", "name": "PLA", "filament_id": "X"},
                      {"vendor": "Bambu Lab", "name": "PLA Basic", "filament_id": "GFA00"}]
    found = await bambu._filament_id(Spool(1, "Bambu Lab", "PLA", "PLA Basic Jade White"))
    assert found == "GFA00"


# --- notifications ---------------------------------------------------------------------------

async def test_missing_sign_in_is_reported(tmp_path):
    ha = FakeHA()
    hub, _smc, bbc = make(tmp_path, [], [], ha=ha)
    bbc.token = ""
    await hub.refresh()
    assert "login" in ha.shown
    bbc.token = "x"
    await hub.refresh()
    assert "login" not in ha.shown


async def test_running_out_sign_in_is_reported(tmp_path):
    ha = FakeHA()
    hub, _smc, bbc = make(tmp_path, [], [], ha=ha)
    soon = int(time.time()) + 3 * 86400
    payload = base64.urlsafe_b64encode(json.dumps({"exp": soon}).encode()).decode().rstrip("=")
    real = Bambu(tmp_path / "t.json")
    real.token = f"h.{payload}.s"
    assert abs(real.expires_at - soon) < 1
    type(bbc).expires_at = property(lambda self: soon)
    try:
        await hub.refresh()
    finally:
        del type(bbc).expires_at
    assert "expiry" in ha.shown


async def test_unreachable_spoolman_is_reported_after_some_checks(tmp_path):
    ha = FakeHA()
    hub, smc, _bbc = make(tmp_path, [], [], ha=ha)

    async def broken():
        raise OSError("nicht erreichbar")

    smc.list_spools = broken
    for _ in range(2):
        await hub.refresh()
    assert "spoolman" not in ha.shown
    await hub.refresh()
    assert "spoolman" in ha.shown
