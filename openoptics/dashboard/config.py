# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""Single source of truth for dashboard configuration."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _default_state_dir() -> Path:
    return Path(os.environ.get("OPENOPTICS_STATE_DIR") or Path.home() / ".openoptics")


@dataclass
class DashboardConfig:
    enabled: bool = True
    host: str = "localhost"
    port: int = 8001
    poll_interval_s: float = 1.0
    state_dir: Path = field(default_factory=_default_state_dir)

    # Live-feed queue size per WebSocket subscriber. When full, oldest is dropped
    # (live view is not lossless by design; full history is always in the DB).
    live_queue_size: int = 256

    @property
    def db_path(self) -> Path:
        return self.state_dir / "dashboard.sqlite3"

    @property
    def media_dir(self) -> Path:
        return self.state_dir / "media"

    @property
    def topos_dir(self) -> Path:
        return self.media_dir / "topos"

    def ensure_dirs(self) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.topos_dir.mkdir(parents=True, exist_ok=True)

    @classmethod
    def from_env(cls) -> "DashboardConfig":
        cfg = cls()
        if v := os.environ.get("OPENOPTICS_DASHBOARD_HOST"):
            cfg.host = v
        if v := os.environ.get("OPENOPTICS_DASHBOARD_PORT"):
            cfg.port = int(v)
        if v := os.environ.get("OPENOPTICS_DASHBOARD_POLL_INTERVAL"):
            cfg.poll_interval_s = float(v)
        return cfg
