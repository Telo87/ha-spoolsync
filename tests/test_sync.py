"""The plan: which side wins, matching, creating, deleting."""

from spoolsync.model import Spool, norm_color
from spoolsync.sync import Link, Options, agreed, plan


def sm(id_, **kw):
    base = {"vendor": "Bambu Lab", "material": "PLA", "name": "PLA Basic", "color": "FFFFFF",
            "total_g": 1000, "remaining_g": 800}
    base.update(kw)
    return Spool(id_, **base)


def kinds(p):
    return [a.kind for a in p.actions]


def linked(s, b):
    return Link(s.id, b.id, agreed(s, b, {}))


def test_equal_sides_need_nothing():
    s, b = sm(1), sm(100)
    assert plan([s], [b], [linked(s, b)], Options()).actions == []


def test_print_on_the_other_printer_goes_to_the_cloud():
    s, b = sm(1), sm(100)
    link = linked(s, b)
    s.remaining_g = 740  # OctoPrint booked 60 g in Spoolman
    p = plan([s], [b], [link], Options())
    assert kinds(p) == ["update_bambu"]
    assert p.actions[0].changes == {"remaining_g": 740}


def test_change_in_the_cloud_goes_to_spoolman():
    s, b = sm(1), sm(100)
    link = linked(s, b)
    b.remaining_g = 700
    b.note = "offen"
    p = plan([s], [b], [link], Options())
    assert kinds(p) == ["update_spoolman"]
    assert p.actions[0].changes == {"remaining_g": 700, "note": "offen"}


def test_conflict_lower_remainder_wins_rest_by_option():
    s, b = sm(1), sm(100)
    link = linked(s, b)
    s.remaining_g, b.remaining_g = 700, 750
    s.name, b.name = "A", "B"
    p = plan([s], [b], [link], Options(conflict_winner="bambu"))
    by = {a.kind: a.changes for a in p.actions}
    assert by["update_bambu"] == {"remaining_g": 700}
    assert by["update_spoolman"] == {"name": "B"}


def test_small_rounding_differences_are_equal():
    s, b = sm(1), sm(100, remaining_g=801)
    assert plan([s], [b], [Link(1, 100, {})], Options()).actions == []


def test_empty_value_never_blanks_the_other_side():
    s, b = sm(1, vendor=""), sm(100)
    p = plan([s], [b], [Link(1, 100, {})], Options(conflict_winner="spoolman"))
    assert p.actions[0].kind == "update_spoolman"
    assert p.actions[0].changes == {"vendor": "Bambu Lab"}


def test_new_spools_are_created_on_the_other_side():
    s = sm(1, material="PETG", color="000000")
    b = sm(100, material="ABS", color="0A2989")
    p = plan([s], [b], [], Options())
    assert kinds(p) == ["create_bambu", "create_spoolman"]


def test_archived_spoolman_spool_is_not_created():
    assert plan([sm(1, archived=True)], [], [], Options()).actions == []


def test_existing_spools_are_matched_instead_of_duplicated():
    s1, s2 = sm(1, remaining_g=300), sm(2, remaining_g=900)
    b1, b2 = sm(100, remaining_g=905), sm(101, remaining_g=290)
    p = plan([s1, s2], [b1, b2], [], Options())
    links = {(a.sm, a.bb) for a in p.actions if a.kind == "link"}
    assert links == {(1, 101), (2, 100)}
    assert "create_bambu" not in kinds(p)


def test_different_colour_is_not_matched():
    p = plan([sm(1)], [sm(100, color="000000")], [], Options())
    assert "link" not in kinds(p)


def test_deleted_in_spoolman_is_deleted_in_the_cloud():
    b = sm(100)
    p = plan([], [b], [Link(1, 100, {})], Options())
    assert kinds(p) == ["delete_bambu"]


def test_deleted_in_the_cloud_is_archived_in_spoolman():
    s = sm(1)
    p = plan([s], [], [Link(1, 100, {})], Options())
    assert kinds(p) == ["archive_spoolman"]


def test_without_deletions_the_spool_comes_back():
    s = sm(1)
    p = plan([s], [], [Link(1, 100, {})], Options(sync_deletions=False))
    assert kinds(p) == ["unlink"]
    assert kinds(plan([s], [], [], Options(sync_deletions=False))) == ["create_bambu"]


def test_mass_disappearance_is_not_taken_as_deletion():
    spools = [sm(i, color=f"00000{i}") for i in range(1, 6)]
    links = [Link(i, 100 + i, {}) for i in range(1, 6)]
    p = plan(spools, [], links, Options())
    assert "archive_spoolman" not in kinds(p)
    assert p.warnings


def test_colour_formats():
    assert norm_color("#ffffffff") == "FFFFFF"
    assert norm_color("0a2989") == "0A2989"
    assert norm_color(None) == ""
