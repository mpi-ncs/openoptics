# Copyright (c) Max-Planck-Gesellschaft zur Förderung der Wissenschaften e.V.
# Developed at the Max Planck Institute for Informatics, Network and Cloud Systems Group
#
# Author: Yiming Lei (ylei@mpi-inf.mpg.de)
#
# License: Creative Commons NC BY SA 4.0
# https://creativecommons.org/licenses/by-nc-sa/4.0/deed.en
"""Event-driven sink for ns-3 ``TraceSource`` snapshots.

Unlike :class:`Collector`, this has no polling thread. The ns-3 backend
connects the :class:`OcsApp`/:class:`TorApp` ``"Snapshot"`` trace sources
to :meth:`on_ocs_snapshot` / :meth:`on_tor_snapshot` via cppyy
``MakeCallback``. Each trace fire invokes the Python callback
synchronously on the main simulation thread (GIL already held), writes
a handful of :class:`MetricSample` rows to the Repository, and pushes
them over the broker to live WebSocket subscribers.

Registered with :class:`DashboardService` via ``register_event_source``
(not ``register_collector``) so the service doesn't try to ``start``/
``stop`` a non-existent polling thread.
"""
from __future__ import annotations

import logging
import time
from typing import Iterable, Optional, Tuple

from ..broker import EventBroker
from ..events import MetricSample
from ..storage.repository import Repository

log = logging.getLogger(__name__)


class Ns3MetricSink:
    """Receives ns-3 snapshot events; persists + broadcasts as MetricSamples."""

    def __init__(self) -> None:
        self._repo: Optional[Repository] = None
        self._broker: Optional[EventBroker] = None
        self._epoch_id: Optional[int] = None

    def bind(self, repo: Repository, broker: EventBroker, epoch_id: int) -> None:
        """Wire repo/broker/epoch_id. Called by DashboardService during
        ``register_event_source``. Also registers the ns-3-specific metric
        types with :meth:`Repository.upsert_metric_type` so the dashboard UI
        gets the right labels, units, and sort order.
        """
        self._repo = repo
        self._broker = broker
        self._epoch_id = epoch_id

        # New metric types introduced by the ns-3 backend. queue_depth and
        # drop_count are already built-in (schema.sql); the rest are added
        # idempotently via upsert.
        repo.upsert_metric_type(
            "queue_bytes",    "Queue Bytes", "bytes", "line",
            sort_order=11,
        )
        repo.upsert_metric_type(
            "ocs_forward",    "OCS Forwarded", "packets", "line",
            sort_order=25,
        )
        repo.upsert_metric_type(
            "tor_forwarded",  "ToR Forwarded", "packets", "line",
            sort_order=26,
        )
        repo.upsert_metric_type(
            "tor_delivered",  "ToR Delivered", "packets", "line",
            sort_order=27,
        )
        repo.upsert_metric_type(
            "queue_peak",     "Peak Queue Depth", "packets", "line",
            sort_order=15,
        )
        repo.upsert_metric_type(
            "queue_peak_bytes", "Peak Queue Bytes", "bytes", "line",
            sort_order=16,
        )
        repo.upsert_metric_type(
            "tor_overflow_drops", "ToR Slice Overflow Drops", "packets",
            "line", sort_order=22,
        )

    # ------------------------------------------------------------------
    # Trace endpoints — invoked by cppyy on the simulation main thread.
    # ------------------------------------------------------------------

    def on_ocs_snapshot(self, sim_time_us, fwd, drop) -> None:
        """OcsApp::m_snapshotTrace payload: (sim_time_us, forward, drop)."""
        if self._repo is None:
            return  # Not bound yet (NullDashboard / uninitialized) — no-op.
        self._persist(
            sim_time_us,
            (
                ("ocs_forward", "ocs", float(fwd)),
                ("drop_count",  "ocs", float(drop)),
            ),
        )

    def on_tor_snapshot(self, sim_time_us, tor_id, fwd, delivered, drops,
                        total_depth, peak_depth, total_bytes, peak_bytes,
                        cq_drops, ingress_from_host, ingress_from_uplink,
                        overflow_drops) -> None:
        """TorApp::m_snapshotTrace payload.

        ``cq_drops`` / ``ingress_from_host`` / ``ingress_from_uplink`` are
        received but not yet persisted — reserved for follow-up metric
        types. (Emitting them now would force the UI to handle unregistered
        metric_types on the first load.)
        """
        if self._repo is None:
            return
        dev = f"tor{tor_id}"
        self._persist(
            sim_time_us,
            (
                ("tor_forwarded",      dev, float(fwd)),
                ("tor_delivered",     dev, float(delivered)),
                ("drop_count",        dev, float(drops)),
                ("queue_depth",       dev, float(total_depth)),
                ("queue_peak",        dev, float(peak_depth)),
                ("queue_bytes",       dev, float(total_bytes)),
                ("queue_peak_bytes",  dev, float(peak_bytes)),
                ("tor_overflow_drops", dev, float(overflow_drops)),
            ),
        )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _persist(
        self,
        sim_time_us: int,
        triples: Iterable[Tuple[str, str, float]],
    ) -> None:
        # Dashboard UI plots X-axis by `timestep`; use sim time in ms so the
        # axis matches the simulation's own clock.
        timestep = int(sim_time_us // 1000)
        now = time.time()
        samples = [
            MetricSample(
                metric_type=metric_type,
                device=device,
                value=value,
                timestep=timestep,
                timestamp=now,
                epoch_id=self._epoch_id,
            )
            for metric_type, device, value in triples
        ]
        try:
            self._repo.insert_samples(samples)
        except Exception:
            log.exception("Ns3MetricSink: insert_samples failed; dropping tick")
            return
        for s in samples:
            self._broker.publish_threadsafe(s)
