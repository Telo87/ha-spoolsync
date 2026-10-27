"""Add-on options (/data/options.json) – environment variables override them for local runs."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

DATA_DIR = Path(os.environ.get("SPOOLSYNC_DATA", "/data"))


@dataclass
class Options:
    spoolman_url: str = "http://homeassistant.local:7912"
    interval_minutes: int = 5
    auto_sync: bool = False
    conflict_winner: str = "spoolman"
    sync_deletions: bool = True
    book_bambu_prints: bool = True
    log_level: str = "info"
    port: int = 8099
    demo: bool = False


def load_options() -> Options:
    opts = Options()
    try:
        data = json.loads((DATA_DIR / "options.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        data = {}
    for key, value in data.items():
        if hasattr(opts, key):
            setattr(opts, key, value)
    if os.environ.get("SPOOLSYNC_SPOOLMAN_URL"):
        opts.spoolman_url = os.environ["SPOOLSYNC_SPOOLMAN_URL"]
    if os.environ.get("SPOOLSYNC_PORT"):
        opts.port = int(os.environ["SPOOLSYNC_PORT"])
    opts.demo = os.environ.get("SPOOLSYNC_DEMO") == "1"
    opts.interval_minutes = max(1, int(opts.interval_minutes))
    if opts.conflict_winner not in ("spoolman", "bambu"):
        opts.conflict_winner = "spoolman"
    return opts
