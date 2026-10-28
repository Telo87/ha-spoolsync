"""Both sides in memory – for trying the interface locally (SPOOLSYNC_DEMO=1) and for the tests."""

from __future__ import annotations

from dataclasses import replace

from .model import Spool


class FakeSpoolman:
    def __init__(self, spools: list[Spool] | None = None):
        self.spools = {s.id: s for s in spools or []}
        self.next_id = max(self.spools, default=0) + 1
        self.calls: list[tuple] = []

    async def list_spools(self) -> list[Spool]:
        return [replace(s) for s in self.spools.values()]

    async def create(self, s: Spool) -> int:
        new = replace(s, id=self.next_id, archived=False, rfid="", extra={})
        self.spools[new.id] = new
        self.next_id += 1
        self.calls.append(("create", new.id))
        return new.id

    async def update(self, current: Spool, changes: dict) -> None:
        self.calls.append(("update", current.id, dict(changes)))
        s = self.spools[current.id]
        for f, v in changes.items():
            setattr(s, f, v)

    async def archive(self, spool_id: int) -> None:
        self.calls.append(("archive", spool_id))
        self.spools[spool_id].archived = True

    async def set_bambu_id(self, s: Spool, bb_id: int) -> None:
        self.calls.append(("bambu_id", s.id, bb_id))
        self.spools[s.id].extra = {**self.spools[s.id].extra, "bambu_id": str(bb_id)}

    async def close(self) -> None:
        pass


class FakeBambu(FakeSpoolman):
    def __init__(self, spools: list[Spool] | None = None, signed_in: bool = True):
        super().__init__(spools)
        self.next_id = max(self.spools, default=7000000) + 1
        self.token = "demo" if signed_in else ""
        self.email = "demo@example.com" if signed_in else ""
        self.region = "global"
        self._pending = ""
        self.task_list: list[dict] = []

    @property
    def signed_in(self) -> bool:
        return bool(self.token)

    @property
    def pending(self) -> str:
        return self._pending

    def sign_out(self) -> None:
        self.token = ""

    async def login(self, email: str, password: str, region: str = "global") -> str:
        self.email = email
        self._pending = "code"
        return "code"

    async def submit_code(self, code: str) -> str:
        self.token = "demo"
        self._pending = ""
        return "ok"

    async def resend_code(self) -> None:
        pass

    async def tasks(self, limit: int = 30) -> list[dict]:
        return list(self.task_list)

    async def delete(self, spool_id: int) -> None:
        self.calls.append(("delete", spool_id))
        del self.spools[spool_id]


def demo_sides() -> tuple[FakeSpoolman, FakeBambu]:
    sm = FakeSpoolman([
        Spool(1, "Bambu Lab", "PLA", "PLA Basic", "FFFFFF", 1000, 812),
        Spool(2, "Bambu Lab", "PETG", "PETG HF", "000000", 1000, 450, note="Trocknen vor Gebrauch"),
        Spool(3, "Generic", "PLA", "PLA Silk", "C0C0C0", 1000, 1000),
        Spool(4, "Generic", "TPU", "TPU 95A", "FF0000", 500, 120, archived=True),
    ])
    bb = FakeBambu([
        Spool(7000001, "Bambu Lab", "PLA", "PLA Basic", "FFFFFF", 1000, 790,
              location="Drucker – AMS 1 Slot 1"),
        Spool(7000002, "Bambu Lab", "PETG", "PETG HF", "000000", 1000, 450),
        Spool(7000003, "Bambu Lab", "ABS", "ABS", "0A2989", 1000, 655),
    ])
    return sm, bb
