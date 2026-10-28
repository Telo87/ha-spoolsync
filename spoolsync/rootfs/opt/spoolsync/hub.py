"""Reads both sides, plans and carries out the sync, remembers the links between the spools."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import replace
from pathlib import Path

from . import sync, usage
from .bambu import AuthRequired
from .config import Options
from .ha import HomeAssistant
from .model import FIELDS, show
from .sync import Link

# tell about a side that cannot be read only after this many checks in a row
FAILS_BEFORE_NOTICE = 3
# warn this long before the sign-in at the cloud runs out
EXPIRY_WARNING_S = 7 * 24 * 3600

_LOG = logging.getLogger(__name__)


class Hub:
    def __init__(self, opts: Options, spoolman, bambu, data_dir: Path, ha=None, colors=None):
        self.opts = opts
        self.spoolman = spoolman
        self.bambu = bambu
        self.ha = ha or HomeAssistant(enabled=False)
        self.colors = colors  # Bambu Lab's colour names, None = not used
        self.links_file = data_dir / "links.json"
        self.never: set[tuple[int, int]] = set()  # pairs separated by hand
        self.links: list[Link] = self._load_links()
        self.fails = {"spoolman": 0, "bambu": 0}
        self.usage_file = data_dir / "usage.json"
        self.usage = self._load_usage()
        self.usage_done: list[int] = []  # print jobs dealt with once the current plan is carried out
        self.sm_spools: list = []
        self.bb_spools: list = []
        self.plan = sync.Plan([])
        self.errors: dict[str, str] = {}
        self.last_check: float | None = None
        self.last_sync: float | None = None
        self.next_run: float | None = None
        self.log: deque = deque(maxlen=200)
        self.lock = asyncio.Lock()
        self._wake = asyncio.Event()

    # --- links ---------------------------------------------------------------------------------

    def _load_links(self) -> list[Link]:
        try:
            data = json.loads(self.links_file.read_text(encoding="utf-8"))
            self.never = {(int(sm), int(bb)) for sm, bb in data.get("never", [])}
            return [Link.from_json(item) for item in data.get("links", [])]
        except (OSError, ValueError, KeyError, TypeError):
            return []

    def _save_links(self) -> None:
        self.links_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.links_file.with_suffix(".tmp")
        tmp.write_text(json.dumps({"links": [link.to_json() for link in self.links],
                                   "never": sorted(self.never)}, indent=1, ensure_ascii=False),
                       encoding="utf-8")
        tmp.replace(self.links_file)

    def _unlink(self, sm_id, bb_id) -> None:
        self.links = [link for link in self.links if not (link.sm == sm_id and link.bb == bb_id)]

    def _link_of(self, sm_id, bb_id) -> Link | None:
        return next((link for link in self.links if link.sm == sm_id and link.bb == bb_id), None)

    async def link(self, sm_id: int, bb_id: int) -> None:
        """Links two spools by hand – an earlier link of either of them ends."""
        if not any(s.id == sm_id for s in self.sm_spools):
            raise ValueError(f"Spoolman-Spule #{sm_id} unbekannt")
        if not any(b.id == bb_id for b in self.bb_spools):
            raise ValueError(f"Bambu-Spule #{bb_id} unbekannt")
        self.links = [link for link in self.links if link.sm != sm_id and link.bb != bb_id]
        self.never.discard((sm_id, bb_id))
        self.links.append(Link(sm_id, bb_id, {}))
        self._save_links()
        self._note("ok", f"Von Hand verknüpft: Spoolman #{sm_id} ↔ Bambu #{bb_id}")

    async def unlink(self, sm_id: int, bb_id: int) -> None:
        """Separates two spools by hand – they are not matched again."""
        self._unlink(sm_id, bb_id)
        self.never.add((sm_id, bb_id))
        self._save_links()
        self._note("ok", f"Von Hand getrennt: Spoolman #{sm_id} ↔ Bambu #{bb_id}")

    def _relink_from_ids(self, sm_by: dict, bb_by: dict) -> None:
        """Links kept in Spoolman's extra field come back, e.g. after a reinstall."""
        linked_sm = {link.sm for link in self.links}
        linked_bb = {link.bb for link in self.links}
        for s in sm_by.values():
            try:
                bb_id = int(s.extra.get("bambu_id") or 0)
            except ValueError:
                continue
            if (bb_id and s.id not in linked_sm and bb_id in bb_by and bb_id not in linked_bb
                    and (s.id, bb_id) not in self.never and not s.archived):
                self.links.append(Link(s.id, bb_id, {}))
                linked_sm.add(s.id)
                linked_bb.add(bb_id)

    async def _store_ids(self) -> None:
        """Writes the linked cloud spool into Spoolman's extra field where it is missing."""
        sm_by = {s.id: s for s in self.sm_spools}
        for link in self.links:
            s = sm_by.get(link.sm)
            if s is None or s.archived or s.extra.get("bambu_id") == str(link.bb):
                continue
            try:
                await self.spoolman.set_bambu_id(s, link.bb)
                s.extra["bambu_id"] = str(link.bb)
            except Exception as err:  # noqa: BLE001 – the links file still has it
                _LOG.warning("Bambu-ID in Spoolman nicht gespeichert: %s", err)
                return
    def _note(self, level: str, text: str) -> None:
        self.log.appendleft({"t": time.time(), "level": level, "text": text})
        getattr(_LOG, "warning" if level == "error" else "info")(text)

    # --- runs ----------------------------------------------------------------------------------

    def _options(self) -> sync.Options:
        return sync.Options(self.opts.conflict_winner, self.opts.sync_deletions)

    async def refresh(self) -> bool:
        """Reads both sides and plans – changes nothing. True when both sides could be read."""
        self.errors = {}
        try:
            self.sm_spools = await self.spoolman.list_spools()
        except Exception as err:  # noqa: BLE001 – shown in the interface
            self.errors["spoolman"] = str(err)
        if not self.bambu.signed_in:
            self.errors["bambu"] = "Nicht bei der Bambu-Cloud angemeldet."
        else:
            try:
                self.bb_spools = await self.bambu.list_spools()
            except AuthRequired as err:
                self.bambu.sign_out()
                self.errors["bambu"] = f"{err} Bitte neu anmelden."
            except Exception as err:  # noqa: BLE001
                self.errors["bambu"] = str(err)
        self.last_check = time.time()
        for side in self.fails:
            self.fails[side] = self.fails[side] + 1 if side in self.errors else 0
        await self._health()
        if self.errors:
            self.plan = sync.Plan([])
            return False
        sm_by = {s.id: s for s in self.sm_spools}
        bb_by = {b.id: b for b in self.bb_spools}
        self._relink_from_ids(sm_by, bb_by)
        for link in self.links:
            s, b = sm_by.get(link.sm), bb_by.get(link.bb)
            if s is not None and b is not None:
                link.snapshot = sync.agreed(s, b, link.snapshot)
        self._save_links()
        # the planner sees copies with the usage already deducted: the new remainder then goes to
        # the other side in the same run
        sm_plan = [replace(s) for s in self.sm_spools]
        bb_plan = [replace(b) for b in self.bb_spools]
        uses, notes = await self._plan_usage({s.id: s for s in sm_plan},
                                             {b.id: b for b in bb_plan}, bb_plan)
        self.plan = sync.plan(sm_plan, bb_plan, self.links, self._options(), self.never)
        self.plan.actions[:0] = uses
        self.plan.warnings += notes
        return True

    # --- usage of the Bambu Lab printers -------------------------------------------------------

    def _load_usage(self) -> dict:
        try:
            data = json.loads(self.usage_file.read_text(encoding="utf-8"))
            return {"since": float(data["since"]), "done": [int(i) for i in data.get("done", [])]}
        except (OSError, ValueError, KeyError, TypeError):
            return {"since": None, "done": []}

    def _save_usage(self) -> None:
        self.usage["done"] = self.usage["done"][-500:]
        self.usage_file.parent.mkdir(parents=True, exist_ok=True)
        self.usage_file.write_text(json.dumps(self.usage), encoding="utf-8")

    async def _plan_usage(self, sm_by: dict, bb_by: dict,
                          bb_spools: list) -> tuple[list[sync.Action], list[str]]:
        self.usage_done = []
        if not self.opts.book_bambu_prints:
            return [], []
        if self.usage["since"] is None:
            # only prints that end from now on – older ones are in the remainders already
            self.usage["since"] = time.time()
            self._save_usage()
        try:
            tasks = await self.bambu.tasks()
        except Exception as err:  # noqa: BLE001 – the spools can still be synced
            return [], [f"Druckaufträge der Bambu-Cloud nicht lesbar: {err}"]
        up = usage.plan_usage(tasks, bb_spools, set(self.usage["done"]),
                              self.usage["since"])
        self.usage_done = up.done
        notes = list(up.notes)
        by_bb = {link.bb: link for link in self.links}
        actions = []
        for use in up.uses:
            b = bb_by[use.bb]
            link = by_bb.get(use.bb)
            s = sm_by.get(link.sm) if link else None
            what = f"„{use.title}“ auf {use.printer}: {use.grams} g"
            if s is not None and not s.archived:
                before = link.snapshot.get("remaining_g")
                if (usage.already_booked(before, b.remaining_g, use.grams)
                        or usage.already_booked(before, s.remaining_g, use.grams)):
                    notes.append(f"{what} sind schon abgezogen – nicht doppelt gebucht.")
                    continue
                if s.remaining_g is None:
                    continue
                new = max(0, s.remaining_g - use.grams)
                actions.append(sync.Action(
                    "use_spoolman", s.id, b.id, changes={"remaining_g": new}, spool=replace(s),
                    task=use.task_id, text=f"Verbrauch buchen – {what} von {s.title()} "
                    f"({s.remaining_g} g → {new} g)"))
                s.remaining_g = new
            elif link is None:
                if b.remaining_g is None:
                    continue
                new = max(0, b.remaining_g - use.grams)
                actions.append(sync.Action(
                    "use_bambu", None, b.id, changes={"remaining_g": new}, spool=replace(b),
                    task=use.task_id, text=f"Verbrauch buchen – {what} von {b.title()} "
                    f"({b.remaining_g} g → {new} g)"))
                b.remaining_g = new
        return actions, notes

    async def run(self) -> dict:
        """Reads, plans and carries out the plan."""
        async with self.lock:
            if not await self.refresh():
                return {"ok": False, "done": 0, "failed": 0}
            done = failed = 0
            failed_tasks: set[int] = set()
            stopped = False
            for action in self.plan.actions:
                try:
                    await self._apply(action)
                    if not action.quiet:
                        done += 1
                        self._note("ok", action.text)
                except AuthRequired as err:
                    self.bambu.sign_out()
                    self._note("error", f"{err} Bitte neu anmelden.")
                    failed += 1
                    stopped = True
                    break
                except Exception as err:  # noqa: BLE001 – the next action may still work
                    failed += 1
                    if action.task is not None:
                        failed_tasks.add(action.task)
                    self._note("error", f"Fehlgeschlagen: {action.text} – {err}")
                self._save_links()
            if not stopped and self.usage_done:
                self.usage["done"] += [t for t in self.usage_done if t not in failed_tasks]
                self._save_usage()
            self.last_sync = time.time()
            if self.plan.actions:
                await self.refresh()  # also sets the agreed values of new links
            if not self.errors:
                await self._store_ids()
            if failed:
                await self.ha.notify("sync", "SpoolSync: Abgleich unvollständig",
                                     f"{failed} Änderung(en) konnten nicht übernommen werden. "
                                     "Einzelheiten stehen im Verlauf von SpoolSync.")
            elif not self.errors:
                await self.ha.dismiss("sync")
            return {"ok": failed == 0, "done": done, "failed": failed}

    async def _health(self) -> None:
        """Notifications in Home Assistant about what keeps the sync from working."""
        b = self.bambu
        if not b.signed_in and not b.pending:
            await self.ha.notify(
                "login", "SpoolSync: Anmeldung bei Bambu Lab nötig",
                "SpoolSync ist nicht (mehr) bei der Bambu-Cloud angemeldet – die Spulen werden "
                "nicht abgeglichen. Bitte SpoolSync öffnen und neu anmelden.")
        else:
            await self.ha.dismiss("login")
        expires = getattr(b, "expires_at", None) if b.signed_in else None
        if expires and expires - time.time() < EXPIRY_WARNING_S:
            day = time.strftime("%d.%m.%Y", time.localtime(expires))
            await self.ha.notify(
                "expiry", "SpoolSync: Anmeldung läuft bald ab",
                f"Die Anmeldung bei der Bambu-Cloud gilt bis {day}. Danach SpoolSync öffnen, "
                "abmelden und neu anmelden.")
        else:
            await self.ha.dismiss("expiry")
        for side, title in (("spoolman", "Spoolman nicht erreichbar"),
                            ("bambu", "Bambu-Cloud nicht erreichbar")):
            if side == "bambu" and not b.signed_in:
                await self.ha.dismiss(side)
            elif self.fails[side] >= FAILS_BEFORE_NOTICE:
                await self.ha.notify(side, f"SpoolSync: {title}",
                                     f"Seit {self.fails[side]} Prüfungen: {self.errors[side]}")
            elif self.fails[side] == 0:
                await self.ha.dismiss(side)

    async def _apply(self, a: sync.Action) -> None:
        if a.kind == "link":
            self.links.append(Link(a.sm, a.bb, {}))
        elif a.kind == "unlink":
            self._unlink(a.sm, a.bb)
        elif a.kind == "create_bambu":
            new_id = await self.bambu.create(a.spool)
            self.links.append(Link(a.sm, new_id, a.spool.values()))
        elif a.kind == "create_spoolman":
            spool = a.spool
            color_name = await self._color_name(spool)
            if color_name:  # "ABS" -> "ABS Azurblau", like the spools named in Spoolman
                spool = replace(spool, name=f"{spool.name or spool.material} {color_name}")
            new_id = await self.spoolman.create(spool)
            self.links.append(Link(new_id, a.bb, {**a.spool.values(),
                                                  "location": a.spool.location}))
        elif a.kind == "update_bambu":
            await self.bambu.update(a.spool, a.changes)
        elif a.kind in ("update_spoolman", "use_spoolman"):
            await self.spoolman.update(a.spool, a.changes)
            link = self._link_of(a.sm, a.bb)
            if link is not None and "location" in a.changes:
                link.snapshot["location"] = a.changes["location"]
        elif a.kind == "use_bambu":
            await self.bambu.update(a.spool, a.changes)
        elif a.kind == "delete_bambu":
            await self.bambu.delete(a.bb)
            self._unlink(a.sm, a.bb)
        elif a.kind == "archive_spoolman":
            await self.spoolman.archive(a.sm)
            if not a.keep_link:
                self._unlink(a.sm, a.bb)
        else:
            raise ValueError(a.kind)

    async def _color_name(self, b) -> str:
        """Bambu Lab's name of the colour of a spool from the cloud ('' if none)."""
        if self.colors is None or b.rfid:  # spools with chip keep the name the AMS gives them
            return ""
        try:
            name = await self.colors.name(b.extra.get("filamentId") or "", b.color)
        except Exception as err:  # noqa: BLE001 – the spool is created without it
            _LOG.warning("Farbname nicht ermittelt: %s", err)
            return ""
        if not name or name.casefold() in (b.name or "").casefold():
            return ""
        return name

    async def loop(self) -> None:
        while True:
            try:
                if self.opts.auto_sync and self.bambu.signed_in:
                    await self.run()
                else:
                    async with self.lock:
                        await self.refresh()
            except Exception:  # noqa: BLE001 – keep the loop alive
                _LOG.exception("Abgleich fehlgeschlagen")
            self.next_run = time.time() + self.opts.interval_minutes * 60
            self._wake.clear()
            try:
                await asyncio.wait_for(self._wake.wait(), self.opts.interval_minutes * 60)
            except TimeoutError:
                pass

    def wake(self) -> None:
        self._wake.set()

    # --- for the interface ---------------------------------------------------------------------

    def state(self) -> dict:
        sm_by = {s.id: s for s in self.sm_spools}
        bb_by = {b.id: b for b in self.bb_spools}
        # pairs the dry run recognised count as linked here, too
        pairs = [(link.sm, link.bb) for link in self.links]
        pairs += [(a.sm, a.bb) for a in self.plan.actions if a.kind == "link"]
        linked_sm = {sm for sm, _ in pairs}
        linked_bb = {bb for _, bb in pairs}
        rows = [_row(sm_by.get(sm), bb_by.get(bb)) for sm, bb in pairs
                if (sm_by.get(sm) and not sm_by[sm].archived)
                or (bb_by.get(bb) and not bb_by[bb].archived)]
        rows += [_row(s, None) for s in self.sm_spools if s.id not in linked_sm and not s.archived]
        rows += [_row(None, b) for b in self.bb_spools if b.id not in linked_bb and not b.archived]
        return {
            "demo": self.opts.demo,
            "auto_sync": self.opts.auto_sync,
            "interval_minutes": self.opts.interval_minutes,
            "conflict_winner": self.opts.conflict_winner,
            "sync_deletions": self.opts.sync_deletions,
            "spoolman": {"url": self.opts.spoolman_url, "error": self.errors.get("spoolman", ""),
                         "count": sum(1 for s in self.sm_spools if not s.archived)},
            "bambu": {"signed_in": self.bambu.signed_in, "email": self.bambu.email,
                      "region": self.bambu.region, "pending": self.bambu.pending,
                      "expires_at": getattr(self.bambu, "expires_at", None),
                      "error": self.errors.get("bambu", ""),
                      "count": sum(1 for b in self.bb_spools if not b.archived)},
            "last_check": self.last_check,
            "last_sync": self.last_sync,
            "next_run": self.next_run,
            "busy": self.lock.locked(),
            "plan": [a.to_json() for a in self.plan.writes],
            "warnings": self.plan.warnings,
            "rows": rows,
            "log": list(self.log)[:50],
        }


def _side(s) -> dict | None:
    if s is None:
        return None
    return {"id": s.id, "title": s.title(), "color": s.color, "archived": s.archived,
            **{f: show(f, getattr(s, f)) for f in FIELDS},
            "remaining_raw": s.remaining_g, "total_raw": s.total_g,
            "location": s.location}


def _row(s, b) -> dict:
    return {"sm": _side(s), "bb": _side(b)}
