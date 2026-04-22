# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""SQLite-backed repository for epochs, metric samples, and metric metadata.

Uses stdlib ``sqlite3`` directly — the schema is small enough that an ORM would
be pure overhead. The only ceremony is turning a cross-thread connection on
(``check_same_thread=False``) and serialising writes through an internal lock,
so the collector thread and the web handlers can share one instance safely.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Sequence

from ..events import MetricSample

SCHEMA_PATH = Path(__file__).parent / "schema.sql"

# Built-in metric types seeded on first startup. Tuple order:
#   (metric_type, display_name, unit, chart_kind, sort_order)
# sort_order drives UI display order (ascending). Extensions can call
# ``Repository.upsert_metric_type(...)`` to register more at runtime.
BUILTIN_METRIC_TYPES: Sequence[tuple] = (
    ("queue_depth", "Queue Depth", "packets", "line", 10),
    ("drop_count",  "Drop Count",  "packets", "line", 20),
    ("ocs_schedule_hit", "OCS Schedule Hits", "packets", "line", 30),
    ("ocs_schedule_miss", "OCS Schedule Misses", "packets", "line", 40),
    ("queue_latency_mean", "Queue Latency (mean)", "ms", "line", 50),
    ("queue_latency_max",  "Queue Latency (max)",  "ms", "line", 51),
    ("ta_reconfig", "TA Queue Activation", "qid", "line", 60),
)


@dataclass
class Epoch:
    id: int
    display_name: str
    created_at: float
    topo_image_url: Optional[str]


@dataclass
class MetricTypeMeta:
    metric_type: str
    display_name: str
    unit: Optional[str]
    chart_kind: str
    sort_order: int = 100


class Repository:
    def __init__(self, db_path: Path):
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            self._db_path, check_same_thread=False, isolation_level=None
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.execute("PRAGMA journal_mode = WAL")
        self._lock = threading.Lock()
        self._init_schema()

    def _init_schema(self) -> None:
        sql = SCHEMA_PATH.read_text()
        with self._lock:
            self._conn.executescript(sql)
            # Forward-compat for DBs created by an older build that predated
            # the sort_order column. SQLite has no ALTER ADD COLUMN IF NOT
            # EXISTS, so check PRAGMA first.
            existing_cols = {
                row["name"] for row in
                self._conn.execute("PRAGMA table_info(metric_type_meta)")
            }
            if "sort_order" not in existing_cols:
                self._conn.execute(
                    "ALTER TABLE metric_type_meta "
                    "ADD COLUMN sort_order INTEGER NOT NULL DEFAULT 100"
                )
            # Seed built-in types. BUILTIN_METRIC_TYPES is the source of truth,
            # so on conflict we refresh all columns — otherwise unit/name
            # changes in code never reach existing DBs.
            for mt in BUILTIN_METRIC_TYPES:
                self._conn.execute(
                    "INSERT INTO metric_type_meta "
                    "(metric_type, display_name, unit, chart_kind, sort_order) "
                    "VALUES (?, ?, ?, ?, ?) "
                    "ON CONFLICT(metric_type) DO UPDATE SET "
                    "display_name = excluded.display_name, "
                    "unit = excluded.unit, "
                    "chart_kind = excluded.chart_kind, "
                    "sort_order = excluded.sort_order",
                    mt,
                )

    # -- epochs ----------------------------------------------------------

    def create_epoch(self, display_name: str) -> Epoch:
        now = time.time()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO epochs (display_name, created_at) VALUES (?, ?)",
                (display_name, now),
            )
            return Epoch(
                id=cur.lastrowid,
                display_name=display_name,
                created_at=now,
                topo_image_url=None,
            )

    def set_epoch_topo_url(self, epoch_id: int, url: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE epochs SET topo_image_url = ? WHERE id = ?", (url, epoch_id)
            )

    def list_epochs(self) -> List[Epoch]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, display_name, created_at, topo_image_url FROM epochs "
                "ORDER BY id ASC"
            ).fetchall()
        return [Epoch(**dict(r)) for r in rows]

    def get_epoch(self, epoch_id: int) -> Optional[Epoch]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, display_name, created_at, topo_image_url FROM epochs "
                "WHERE id = ?",
                (epoch_id,),
            ).fetchone()
        return Epoch(**dict(row)) if row else None

    def latest_epoch(self) -> Optional[Epoch]:
        with self._lock:
            row = self._conn.execute(
                "SELECT id, display_name, created_at, topo_image_url FROM epochs "
                "ORDER BY id DESC LIMIT 1"
            ).fetchone()
        return Epoch(**dict(row)) if row else None

    def next_epoch_display_name(self, seed: str) -> str:
        """Return ``seed`` or ``seed (N)`` such that the result is unique."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT display_name FROM epochs WHERE display_name LIKE ?",
                (f"{seed}%",),
            ).fetchall()
        taken = {r["display_name"] for r in rows}
        if seed not in taken:
            return seed
        n = 1
        while f"{seed} ({n})" in taken:
            n += 1
        return f"{seed} ({n})"

    def list_epochs_older_than(self, cutoff_ts: float) -> List[Epoch]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, display_name, created_at, topo_image_url FROM epochs "
                "WHERE created_at < ? ORDER BY id ASC",
                (cutoff_ts,),
            ).fetchall()
        return [Epoch(**dict(r)) for r in rows]

    def delete_epochs(self, epoch_ids: Iterable[int]) -> int:
        """Delete the given epochs. Samples cascade via FK. Returns count."""
        ids = list(epoch_ids)
        if not ids:
            return 0
        placeholders = ",".join("?" for _ in ids)
        with self._lock:
            cur = self._conn.execute(
                f"DELETE FROM epochs WHERE id IN ({placeholders})", ids
            )
            return cur.rowcount

    # -- metric samples --------------------------------------------------

    def insert_samples(self, samples: Iterable[MetricSample]) -> None:
        batch = [
            (
                s.epoch_id,
                s.metric_type,
                s.device,
                json.dumps(s.labels, sort_keys=True),
                s.value,
                s.timestep,
                s.timestamp,
            )
            for s in samples
        ]
        if not batch:
            return
        with self._lock:
            self._conn.executemany(
                "INSERT INTO metric_samples "
                "(epoch_id, metric_type, device, labels_json, value, timestep, timestamp) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                batch,
            )

    def query_samples(
        self,
        epoch_id: int,
        metric_type: Optional[str] = None,
        device: Optional[str] = None,
    ) -> List[MetricSample]:
        sql = (
            "SELECT epoch_id, metric_type, device, labels_json, value, timestep, timestamp "
            "FROM metric_samples WHERE epoch_id = ?"
        )
        args: list = [epoch_id]
        if metric_type is not None:
            sql += " AND metric_type = ?"
            args.append(metric_type)
        if device is not None:
            sql += " AND device = ?"
            args.append(device)
        sql += " ORDER BY timestep ASC"
        with self._lock:
            rows = self._conn.execute(sql, args).fetchall()
        return [
            MetricSample(
                metric_type=r["metric_type"],
                device=r["device"],
                value=r["value"],
                timestep=r["timestep"],
                timestamp=r["timestamp"],
                epoch_id=r["epoch_id"],
                labels=json.loads(r["labels_json"]),
            )
            for r in rows
        ]

    def distinct_devices(self, epoch_id: int) -> List[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT DISTINCT device FROM metric_samples WHERE epoch_id = ? ORDER BY device",
                (epoch_id,),
            ).fetchall()
        return [r["device"] for r in rows]

    # -- metric type metadata -------------------------------------------

    def list_metric_types(self) -> List[MetricTypeMeta]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT metric_type, display_name, unit, chart_kind, sort_order "
                "FROM metric_type_meta "
                "ORDER BY sort_order ASC, metric_type ASC"
            ).fetchall()
        return [MetricTypeMeta(**dict(r)) for r in rows]

    def upsert_metric_type(
        self,
        metric_type: str,
        display_name: str,
        unit: Optional[str] = None,
        chart_kind: str = "line",
        sort_order: int = 100,
    ) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO metric_type_meta "
                "(metric_type, display_name, unit, chart_kind, sort_order) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(metric_type) DO UPDATE SET "
                "  display_name = excluded.display_name, "
                "  unit = excluded.unit, "
                "  chart_kind = excluded.chart_kind, "
                "  sort_order = excluded.sort_order",
                (metric_type, display_name, unit, chart_kind, sort_order),
            )

    def close(self) -> None:
        with self._lock:
            self._conn.close()
