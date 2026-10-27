"""How a Spoolman spool looks in the Bambu apps and back."""

from spoolsync.bambu import Bambu
from spoolsync.model import Spool, type_name
from spoolsync.spoolman import Spoolman, to_spool


def test_colour_names_get_the_material_in_front():
    assert type_name("Turquoise", "PLA+") == "PLA+ Turquoise"
    assert type_name("PLA Basic", "PLA") == "PLA Basic"
    assert type_name("Silk PLA+", "PLA+") == "Silk PLA+"
    assert type_name("Turquoise", "") == "Turquoise"
    assert type_name("", "PETG") == "PETG"


def test_spoolman_spool_as_the_apps_show_it():
    s = to_spool({"id": 3, "initial_weight": 1100, "remaining_weight": 1100.4, "comment": None,
                  "filament": {"id": 9, "name": "Turquoise", "material": "PLA",
                               "color_hex": "38bac0", "weight": 1100,
                               "vendor": {"id": 2, "name": "JAYO"}}})
    assert (s.vendor, s.material, s.name, s.color, s.total_g, s.remaining_g) == (
        "JAYO", "PLA", "PLA Turquoise", "38BAC0", 1100, 1100)


class RecordingSpoolman(Spoolman):
    def __init__(self, filaments):
        super().__init__("http://spoolman")
        self.sent = []
        self._filaments = filaments
        self._vendors = [{"id": 2, "name": "JAYO"}]

    async def _req(self, method, path, **kwargs):
        self.sent.append((method, path, kwargs.get("json")))
        if method == "POST" and path == "/filament":
            return {"id": 99, **kwargs["json"]}
        return {}


async def test_colour_change_keeps_the_spoolman_filament_name():
    old = {"id": 9, "name": "Turquoise", "material": "PLA", "color_hex": "38BAC0",
           "density": 1.24, "diameter": 1.75, "vendor": {"id": 2, "name": "JAYO"}}
    sm = RecordingSpoolman([old])
    current = to_spool({"id": 3, "initial_weight": 1100, "remaining_weight": 900,
                        "filament": old})
    await sm.update(current, {"color": "FF0000"})
    created = next(body for method, path, body in sm.sent if path == "/filament")
    assert created["name"] == "Turquoise" and created["color_hex"] == "FF0000"
    assert ("PATCH", "/spool/3", {"filament_id": 99}) in sm.sent


async def test_other_brands_get_the_generic_profile(tmp_path):
    bambu = Bambu(tmp_path / "b.json")
    bambu._catalog = [{"vendor": "Bambu Lab", "name": "PLA Basic", "filament_id": "GFA00"}]
    assert await bambu._filament_id(Spool(1, "Bambu Lab", "PLA", "PLA Basic")) == "GFA00"
    assert await bambu._filament_id(Spool(1, "JAYO", "PLA", "PLA")) == "GFL99"
    assert await bambu._filament_id(Spool(1, "JAYO", "PETG", "PETG")) == "GFG99"
    assert await bambu._filament_id(Spool(1, "JAYO", "PLA+", "PLA+ Turquoise")) == "GFL99"
    assert await bambu._filament_id(Spool(1, "JAYO", "PEEK", "PEEK")) == ""
