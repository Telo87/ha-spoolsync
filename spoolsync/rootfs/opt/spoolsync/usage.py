"""Filament used by prints on the Bambu Lab printers, from the print history of the cloud.

The cloud does not deduct anything from spools without RFID chip: only the AMS reports the
remainder of Bambu Lab spools with chip. So the grams of every finished print are booked onto the
spool that sits in the AMS slot the print used (as assigned in Bambu Studio / Bambu Handy).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from .model import Spool

TASK_FINISHED = 2
TASK_FAILED = 3  # also cancelled


@dataclass
class Use:
    task_id: int
    bb: int  # spool in the filament library
    grams: int
    title: str
    printer: str


@dataclass
class UsagePlan:
    uses: list[Use]
    done: list[int]  # task ids that are dealt with once this plan is carried out
    notes: list[str]


def end_time(task: dict) -> float | None:
    text = task.get("endTime")
    if not text:
        return None
    try:
        return datetime.fromisoformat(str(text)).timestamp()
    except ValueError:
        return None


def slot_of(flat) -> tuple[int, int] | None:
    """Flat AMS index of the print history -> (amsId, slotId) of the filament library."""
    if not isinstance(flat, int) or isinstance(flat, bool):
        return None
    if 0 <= flat < 16:  # AMS / AMS 2 Pro: 4 slots each
        return flat // 4, flat % 4
    if 16 <= flat < 24:  # AMS HT: one slot each, units 128 and up
        return 128 + flat - 16, 0
    return None


def mounted(spools: list[Spool], dev_id: str, ams_id: int, slot_id: int) -> Spool | None:
    for s in spools:
        e = s.extra
        if (e.get("inPrinter") and str(e.get("devId") or "") == str(dev_id)
                and str(e.get("amsId")) == str(ams_id) and str(e.get("slotId")) == str(slot_id)):
            return s
    return None


def plan_usage(tasks: list[dict], bb_spools: list[Spool], done: set[int],
               since: float) -> UsagePlan:
    uses: list[Use] = []
    finished: list[int] = []
    notes: list[str] = []
    for task in tasks:
        try:
            task_id = int(task.get("id"))
        except (TypeError, ValueError):
            continue
        if task_id in done:
            continue
        status = task.get("status")
        ended = end_time(task)
        if status not in (TASK_FINISHED, TASK_FAILED) or ended is None:
            continue  # still running, or unknown
        if ended < since:
            continue  # before SpoolSync started booking
        title = task.get("title") or "Druck"
        printer = task.get("deviceName") or "Drucker"
        finished.append(task_id)
        if status == TASK_FAILED:
            notes.append(f"„{title}“ auf {printer} wurde abgebrochen – der Verbrauch bis dahin ist "
                         "nicht bekannt und wird nicht gebucht.")
            continue
        for item in task.get("amsDetailMapping") or []:
            try:
                grams = round(float(item.get("weight") or 0))
            except (TypeError, ValueError):
                continue
            if grams <= 0:
                continue
            slot = slot_of(item.get("ams"))
            spool = mounted(bb_spools, task.get("deviceId"), *slot) if slot else None
            if spool is None:
                notes.append(f"„{title}“ auf {printer}: {grams} g aus einem Slot ohne zugeordnete "
                             "Spule – in Bambu Studio die Spule dem AMS-Slot zuordnen.")
                continue
            if spool.rfid:
                continue  # the AMS reports the remainder of spools with chip itself
            uses.append(Use(task_id, spool.id, grams, title, printer))
    return UsagePlan(uses, finished, notes)


def already_booked(before: int | None, now: int | None, grams: int) -> bool:
    """Did the remaining weight drop by about the print's grams already (booked elsewhere)?"""
    if before is None or now is None or grams <= 0:
        return False
    drop = before - now
    return drop > 0 and abs(drop - grams) <= max(3, grams * 0.15)
