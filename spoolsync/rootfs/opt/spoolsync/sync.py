"""Decides what has to change so both sides show the same spools.

The plan is pure: it only looks at the spools of both sides and the links remembered from the last
run, so it can be shown as a dry run before anything is written.

Per linked pair and value: the side whose value differs from the value both sides agreed on last
time was changed and wins. Changed on both sides (or no agreed value yet) is a conflict: the lower
remaining weight wins (filament only gets used up), every other value comes from the configured
side.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .model import FIELDS, LABELS, WEIGHTS, Spool, same, show

SPOOLMAN = "spoolman"
BAMBU = "bambu"
_MISSING = object()


@dataclass
class Link:
    sm: int
    bb: int
    # values both sides agreed on at the last run
    snapshot: dict = field(default_factory=dict)

    def to_json(self) -> dict:
        return {"sm": self.sm, "bb": self.bb, "snapshot": self.snapshot}

    @classmethod
    def from_json(cls, data: dict) -> Link:
        return cls(int(data["sm"]), int(data["bb"]), dict(data.get("snapshot") or {}))


@dataclass
class Options:
    conflict_winner: str = SPOOLMAN
    sync_deletions: bool = True


@dataclass
class Action:
    kind: str  # link, unlink, create_bambu, create_spoolman, update_bambu, update_spoolman,
    #            delete_bambu, archive_spoolman, use_spoolman, use_bambu
    sm: int | None = None
    bb: int | None = None
    changes: dict = field(default_factory=dict)
    text: str = ""
    spool: Spool | None = None  # the spool to copy (create) or the one being changed (update)
    keep_link: bool = False
    task: int | None = None  # print job a usage booking comes from

    @property
    def quiet(self) -> bool:
        """Only bookkeeping, nothing is written to Spoolman or the cloud."""
        return self.kind in ("link", "unlink")

    def to_json(self) -> dict:
        return {"kind": self.kind, "sm": self.sm, "bb": self.bb, "text": self.text,
                "quiet": self.quiet}


@dataclass
class Plan:
    actions: list[Action]
    warnings: list[str] = field(default_factory=list)

    @property
    def writes(self) -> list[Action]:
        return [a for a in self.actions if not a.quiet]


def plan(sm_spools: list[Spool], bb_spools: list[Spool], links: list[Link],
         opts: Options) -> Plan:
    sm_by = {s.id: s for s in sm_spools}
    bb_by = {b.id: b for b in bb_spools}
    actions: list[Action] = []
    warnings: list[str] = []

    # A side that suddenly misses most of its linked spools rather has a problem than a user who
    # deleted them all: then nothing is deleted or archived in this run.
    deletions = opts.sync_deletions
    for name, by, key in (("Spoolman", sm_by, "sm"), ("Bambu-Cloud", bb_by, "bb")):
        gone = sum(1 for link in links if getattr(link, key) not in by)
        if links and gone >= 3 and gone > len(links) / 2:
            deletions = False
            warnings.append(f"{gone} von {len(links)} verknüpften Spulen fehlen in {name} – "
                            "Löschungen werden in diesem Durchlauf nicht übernommen.")

    pairs = [(link.sm, link.bb, link.snapshot) for link in links]
    linked_sm = {link.sm for link in links}
    linked_bb = {link.bb for link in links}
    free_sm = [s for s in sm_spools if s.id not in linked_sm and not s.archived]
    free_bb = [b for b in bb_spools if b.id not in linked_bb and not b.archived]

    for s, b in match(free_sm, free_bb):
        actions.append(Action("link", s.id, b.id, text=f"Verknüpfen: {s.title()} "
                              f"(Spoolman #{s.id} ↔ Bambu #{b.id})"))
        pairs.append((s.id, b.id, {}))
        free_sm.remove(s)
        free_bb.remove(b)

    for sm_id, bb_id, snapshot in pairs:
        actions += _pair(sm_id, bb_id, sm_by.get(sm_id), bb_by.get(bb_id), snapshot, opts,
                         deletions)

    for s in free_sm:
        actions.append(Action("create_bambu", sm=s.id, spool=s,
                              text=f"In der Bambu-Cloud anlegen: {_describe(s)}"))
    for b in free_bb:
        actions.append(Action("create_spoolman", bb=b.id, spool=b,
                              text=f"In Spoolman anlegen: {_describe(b)}"))
    return Plan(actions, warnings)


def _pair(sm_id: int, bb_id: int, s: Spool | None, b: Spool | None, snapshot: dict,
          opts: Options, deletions: bool) -> list[Action]:
    if s is None and b is None:
        return [Action("unlink", sm_id, bb_id, text="Verknüpfung entfernt (beide Seiten weg)")]
    if s is None:
        if deletions and not b.archived:
            return [Action("delete_bambu", sm_id, bb_id, spool=b, text="Aus der Bambu-Cloud "
                           f"löschen: {b.title()} (in Spoolman gelöscht)")]
        return [Action("unlink", sm_id, bb_id, text=f"Verknüpfung gelöst: {b.title()}")]
    if b is None:
        if deletions and not s.archived:
            return [Action("archive_spoolman", sm_id, bb_id, spool=s, text="In Spoolman "
                           f"archivieren: {s.title()} (in der Bambu-Cloud gelöscht)")]
        return [Action("unlink", sm_id, bb_id, text=f"Verknüpfung gelöst: {s.title()}")]
    if s.archived or b.archived:
        if s.archived and not b.archived and deletions:
            return [Action("delete_bambu", sm_id, bb_id, spool=b, text="Aus der Bambu-Cloud "
                           f"löschen: {b.title()} (in Spoolman archiviert)")]
        if b.archived and not s.archived and deletions:
            return [Action("archive_spoolman", sm_id, bb_id, spool=s, keep_link=True,
                           text=f"In Spoolman archivieren: {s.title()} (in der Bambu-Cloud "
                           "als leer/archiviert markiert)")]
        return []

    to_sm: dict = {}
    to_bb: dict = {}
    for f in FIELDS:
        sv, bv = getattr(s, f), getattr(b, f)
        if same(f, sv, bv):
            continue
        old = snapshot.get(f, _MISSING)
        sm_changed = old is _MISSING or not same(f, sv, old)
        bb_changed = old is _MISSING or not same(f, bv, old)
        if sm_changed and not bb_changed:
            winner = SPOOLMAN
            deliberate = True
        elif bb_changed and not sm_changed:
            winner = BAMBU
            deliberate = True
        else:
            deliberate = False
            if f == "remaining_g" and sv is not None and bv is not None:
                winner = SPOOLMAN if sv < bv else BAMBU
            else:
                winner = opts.conflict_winner
        value = sv if winner == SPOOLMAN else bv
        if _empty(value) and not (deliberate and f == "note"):
            # never blank out a value on the other side – an empty value is a missing one
            winner = BAMBU if winner == SPOOLMAN else SPOOLMAN
            value = sv if winner == SPOOLMAN else bv
            if _empty(value):
                continue
        if winner == SPOOLMAN:
            to_bb[f] = value
        else:
            to_sm[f] = value

    actions = []
    if to_bb:
        actions.append(Action("update_bambu", sm_id, bb_id, changes=to_bb, spool=b,
                              text=f"Bambu-Cloud ändern – {b.title()}: "
                              + _changes_text(b, to_bb)))
    if to_sm:
        actions.append(Action("update_spoolman", sm_id, bb_id, changes=to_sm, spool=s,
                              text=f"Spoolman ändern – {s.title()}: "
                              + _changes_text(s, to_sm)))
    return actions


def agreed(s: Spool, b: Spool, snapshot: dict) -> dict:
    """The new snapshot of a pair: every value both sides now show, the rest stays as it was."""
    result = dict(snapshot)
    for f in FIELDS:
        sv, bv = getattr(s, f), getattr(b, f)
        if same(f, sv, bv):
            result[f] = sv
    return result


def match(free_sm: list[Spool], free_bb: list[Spool]) -> list[tuple[Spool, Spool]]:
    """Pairs of not yet linked spools that are most likely the same physical spool.

    Required: same material and colour, and the same vendor where both know it. The rest (RFID,
    name, weights) only ranks the candidates.
    """
    candidates = []
    for s in free_sm:
        for b in free_bb:
            score = _score(s, b)
            if score is not None:
                candidates.append((score, s.id, b.id, s, b))
    candidates.sort(key=lambda c: (-c[0], c[1], c[2]))
    used_sm: set[int] = set()
    used_bb: set[int] = set()
    pairs = []
    for _score_, _sid, _bid, s, b in candidates:
        if s.id in used_sm or b.id in used_bb:
            continue
        used_sm.add(s.id)
        used_bb.add(b.id)
        pairs.append((s, b))
    return pairs


def _score(s: Spool, b: Spool) -> float | None:
    if s.rfid and b.rfid and s.rfid.casefold() == b.rfid.casefold():
        return 1000.0
    if not same("material", s.material, b.material) or not s.material:
        return None
    if not s.color or not b.color or s.color != b.color:
        return None
    if s.vendor and b.vendor and not same("vendor", s.vendor, b.vendor):
        return None
    score = 10.0
    if same("name", s.name, b.name):
        score += 5
    for f in WEIGHTS:
        sv, bv = getattr(s, f), getattr(b, f)
        if sv is not None and bv is not None:
            if same(f, sv, bv):
                score += 3
            else:
                score -= min(abs(sv - bv) / 100, 3)
    return score


def _empty(value) -> bool:
    return value is None or value == ""


def _changes_text(current: Spool, changes: dict) -> str:
    return ", ".join(f"{LABELS[f]} {show(f, getattr(current, f))} → {show(f, v)}"
                     for f, v in changes.items())


def _describe(s: Spool) -> str:
    text = s.title()
    if s.total_g is not None:
        text += f", {s.total_g} g"
    if s.remaining_g is not None:
        text += f", Rest {s.remaining_g} g"
    return text
