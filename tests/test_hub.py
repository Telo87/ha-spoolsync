"""Whole runs against both sides in memory, including the prints of the Bambu Lab printer."""

import time

from spoolsync.config import Options
from spoolsync.demo import FakeBambu, FakeSpoolman
from spoolsync.hub import Hub
from spoolsync.model import Spool


def spool(id_, remaining=800, **kw):
    return Spool(id_, "Generic", "PLA", "PLA Matt", kw.pop("color", "FFFFFF"), 1000, remaining, **kw)


def mounted(id_, remaining=800, rfid=""):
    return spool(id_, remaining, rfid=rfid, extra={"inPrinter": True, "devId": "SN1",
                                                   "amsId": 0, "slotId": "1",
                                                   "deviceName": "H2C"})


def task(task_id, grams, flat=1, status=2, ended=None):
    end = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ended or time.time() + 60))
    return {"id": task_id, "status": status, "endTime": end, "deviceId": "SN1",
            "deviceName": "H2C", "title": "Halter",
            "amsDetailMapping": [{"ams": flat, "weight": grams}]}


def make(tmp_path, sm_spools, bb_spools, **opts):
    smc, bbc = FakeSpoolman(sm_spools), FakeBambu(bb_spools)
    return Hub(Options(**opts), smc, bbc, tmp_path), smc, bbc


async def test_first_run_links_and_creates(tmp_path):
    hub, _smc, bbc = make(tmp_path, [spool(1), spool(2, color="000000")], [spool(100)])
    result = await hub.run()
    assert result["ok"]
    assert len(bbc.spools) == 2  # spool 2 created in the cloud
    assert min((link.sm, link.bb) for link in hub.links) == (1, 100)
    assert hub.plan.writes == []  # afterwards both sides are equal


async def test_spool_created_in_the_cloud_appears_in_spoolman(tmp_path):
    hub, smc, _bbc = make(tmp_path, [], [spool(100, 650, color="00FF00")])
    await hub.run()
    created = list(smc.spools.values())
    assert len(created) == 1 and created[0].remaining_g == 650 and created[0].color == "00FF00"


async def test_octoprint_usage_reaches_the_cloud(tmp_path):
    hub, smc, bbc = make(tmp_path, [spool(1)], [spool(100)])
    await hub.run()
    smc.spools[1].remaining_g = 735
    await hub.run()
    assert bbc.spools[100].remaining_g == 735


async def test_print_on_the_bambu_printer_is_booked_once(tmp_path):
    hub, smc, bbc = make(tmp_path, [spool(1)], [mounted(100)])
    await hub.run()  # links, starts the booking window
    bbc.task_list = [task(55, 42)]
    await hub.run()
    assert smc.spools[1].remaining_g == 758
    assert bbc.spools[100].remaining_g == 758  # and the cloud shows it, too
    await hub.run()
    assert smc.spools[1].remaining_g == 758  # not booked twice


async def test_dry_run_does_not_book(tmp_path):
    hub, smc, bbc = make(tmp_path, [spool(1)], [mounted(100)])
    await hub.run()
    bbc.task_list = [task(55, 42)]
    await hub.refresh()
    assert [a.kind for a in hub.plan.writes] == ["use_spoolman", "update_bambu"]
    assert smc.spools[1].remaining_g == 800
    assert hub.state()["rows"][0]["sm"]["remaining_raw"] == 800  # display shows the real value


async def test_rfid_spools_are_left_to_the_ams(tmp_path):
    hub, smc, bbc = make(tmp_path, [spool(1)], [mounted(100, rfid="ABC")])
    await hub.run()
    bbc.task_list = [task(55, 42)]
    await hub.run()
    assert smc.spools[1].remaining_g == 800


async def test_usage_already_booked_elsewhere_is_skipped(tmp_path):
    hub, smc, bbc = make(tmp_path, [spool(1)], [mounted(100)])
    await hub.run()
    bbc.spools[100].remaining_g = 759  # Studio already reported ~42 g less
    bbc.task_list = [task(55, 42)]
    await hub.run()
    assert smc.spools[1].remaining_g == 759


async def test_prints_before_the_start_are_ignored(tmp_path):
    hub, smc, bbc = make(tmp_path, [spool(1)], [mounted(100)])
    bbc.task_list = [task(55, 42, ended=time.time() - 3600)]
    await hub.run()
    await hub.run()
    assert smc.spools[1].remaining_g == 800


async def test_slot_without_spool_is_reported(tmp_path):
    hub, _smc, bbc = make(tmp_path, [spool(1)], [mounted(100)])
    await hub.run()
    bbc.task_list = [task(55, 42, flat=3)]
    await hub.refresh()
    assert any("ohne zugeordnete Spule" in w for w in hub.plan.warnings)


async def test_links_survive_a_restart(tmp_path):
    hub, smc, bbc = make(tmp_path, [spool(1)], [spool(100)])
    await hub.run()
    again = Hub(Options(), smc, bbc, tmp_path)
    assert [(link.sm, link.bb) for link in again.links] == [(1, 100)]


async def test_colour_name_goes_to_the_cloud_once(tmp_path):
    s = spool(1)
    s.label = "Turquoise"
    hub, smc, bbc = make(tmp_path, [s], [spool(100)])
    await hub.run()
    assert bbc.spools[100].label == "Turquoise"
    bbc.spools[100].label = ""  # the cloud may not report it back
    await hub.refresh()
    assert hub.plan.writes == []
    smc.spools[1].label = "Türkis"  # renamed in Spoolman
    await hub.run()
    assert bbc.spools[100].label == "Türkis"


async def test_new_cloud_spool_gets_the_colour_name(tmp_path):
    s = spool(1)
    s.label = "Turquoise"
    hub, _smc, bbc = make(tmp_path, [s], [])
    await hub.run()
    assert next(iter(bbc.spools.values())).label == "Turquoise"
